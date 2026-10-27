#!/usr/bin/env python3
"""Merge exact iOS root + App Cryptex trust-cache CDHashes for Marble AMFI.

Reads both trust caches from the pinned iPhone10,3 IPSW using the matching
BuildManifest, verifies their Apple manifest digests and pinned SHA256 values,
and emits a standalone include plus provenance manifest. This does not grant
trust by path and does not modify XNU sources.
"""
from __future__ import annotations

import bisect
import hashlib
import json
from pathlib import Path
import plistlib
import struct
import zipfile


LAB = Path(__file__).resolve().parents[1]
RESTORE = LAB / "research/iphone16-restore-input"
IPSW = RESTORE / "iPhone10,3-iPhone10,6_16.7.16_20H392_Restore.ipsw"
BUILD_MANIFEST = RESTORE / "BuildManifest.plist"
STAGE = LAB / "research/marble8796-20261024/cryptex-amfi-stage"

EXPECTED_BUILD_MANIFEST_SHA256 = "2d1452103a2f5ad71cb78d94454977fc70632472201980a468c247fba14b10b7"
EXPECTED_ROOT_SHA256 = "63e01c03b31e1532a5581a24865490673f0b5c297b0199fe0095637c6100ef4b"
EXPECTED_APP_SHA256 = "4e5fc21a171e7fc0e05698c83b9c080307e7cf57a3e88b09cfe0b4e135674067"
EXPECTED_ROOT_COUNT = 2760
EXPECTED_APP_COUNT = 30
WEBBOOKMARKS_ARM64_CDHASH = bytes.fromhex("b0a439a33ae99ae3ca1bc102fe61802394582d36")
WEBBOOKMARKS_ARM64E_CDHASH = bytes.fromhex("131abafed0f4a9bae2be878fb632ce5e174002a5")
ROOT_COMPONENT = "StaticTrustCache"
APP_COMPONENT = "Cryptex1,AppTrustCache"
ROOT_PATH = "Firmware/087-86698-044.dmg.trustcache"
APP_PATH = "Firmware/087-86715-047.dmg.trustcache"


def read_tlv(data: bytes, offset: int) -> tuple[int, int, int]:
    if offset + 2 > len(data):
        raise ValueError("truncated TLV header")
    tag, length = data[offset:offset + 2]
    start = offset + 2
    if length & 0x80:
        count = length & 0x7f
        if not 0 < count <= 4 or start + count > len(data):
            raise ValueError("invalid TLV long-form length")
        length = int.from_bytes(data[start:start + count], "big")
        start += count
    end = start + length
    if end > len(data):
        raise ValueError("TLV length exceeds buffer")
    return tag, start, end


def parse_trustcache(data: bytes, label: str) -> tuple[int, list[bytes]]:
    tag, pos, end = read_tlv(data, 0)
    if tag != 0x30 or end != len(data):
        raise ValueError(f"{label}: not a complete IM4P sequence")
    items: list[tuple[int, bytes]] = []
    while pos < end:
        item_tag, start, next_pos = read_tlv(data, pos)
        items.append((item_tag, data[start:next_pos]))
        pos = next_pos
    if (len(items) != 4 or items[:3] not in (
            [(0x16, b"IM4P"), (0x16, b"trst"), (0x16, b"1")],
            [(0x16, b"IM4P"), (0x16, b"trca"), (0x16, b"1")])
            or items[3][0] != 0x04):
        raise ValueError(f"{label}: unexpected IM4P trust-cache wrapper")
    payload = items[3][1]
    if len(payload) < 24:
        raise ValueError(f"{label}: truncated trust-cache payload")
    version, = struct.unpack_from("<I", payload, 0)
    count, = struct.unpack_from("<I", payload, 20)
    if version != 2 or len(payload) != 24 + count * 24:
        raise ValueError(f"{label}: unsupported version/length ({version}, {len(payload)}, {count})")
    entries = [payload[24 + i * 24:48 + i * 24] for i in range(count)]
    if any(len(entry) != 24 or entry[20] not in (1, 2, 3, 4) for entry in entries):
        raise ValueError(f"{label}: malformed CDHash/type entries")
    keys = [entry[:21] for entry in entries]
    if len(set(keys)) != len(keys):
        raise ValueError(f"{label}: duplicate CDHash/type entries")
    return version, keys


def allow(keys: list[bytes], candidate: bytes) -> bool:
    index = bisect.bisect_left(keys, candidate)
    return index < len(keys) and keys[index] == candidate


def main() -> None:
    if not IPSW.is_file() or not BUILD_MANIFEST.is_file():
        raise SystemExit(f"missing pinned IPSW or BuildManifest under {RESTORE}")
    build_manifest_bytes = BUILD_MANIFEST.read_bytes()
    build_manifest_sha = hashlib.sha256(build_manifest_bytes).hexdigest()
    if build_manifest_sha != EXPECTED_BUILD_MANIFEST_SHA256:
        raise SystemExit(f"BuildManifest SHA256 mismatch: {build_manifest_sha}")
    manifest = plistlib.loads(build_manifest_bytes)
    if (manifest.get("ProductVersion"), manifest.get("ProductBuildVersion")) != ("16.7.16", "20H392"):
        raise SystemExit("BuildManifest is not iOS 16.7.16/20H392")

    identities = [identity for identity in manifest["BuildIdentities"]
                  if identity.get("Info", {}).get("DeviceClass") == "d22ap"
                  and identity.get("Info", {}).get("Variant") == "Customer Erase Install (IPSW)"]
    if len(identities) != 1:
        raise SystemExit(f"expected one iPhone10,3 D22AP erase identity; found {len(identities)}")
    identity = identities[0]
    components = identity["Manifest"]

    def component(component_name: str, expected_path: str, expected_sha256: str) -> tuple[bytes, dict]:
        record = components.get(component_name)
        if not record or record.get("Info", {}).get("Path") != expected_path:
            raise SystemExit(f"BuildManifest mapping mismatch for {component_name}")
        # Older manifest entries (including StaticTrustCache) omit HashMethod;
        # Digest is nevertheless the standard 48-byte SHA-384 value. If the
        # field is present, require it to agree.
        hash_method = record.get("Info", {}).get("HashMethod")
        if hash_method not in (None, "sha2-384") or len(record.get("Digest", b"")) != 48:
            raise SystemExit(f"unexpected BuildManifest digest method for {component_name}")
        with zipfile.ZipFile(IPSW, "r") as archive:
            try:
                data = archive.read(expected_path)
            except KeyError as exc:
                raise SystemExit(f"IPSW missing {expected_path}") from exc
        got_sha256 = hashlib.sha256(data).hexdigest()
        if got_sha256 != expected_sha256:
            raise SystemExit(f"{component_name} SHA256 mismatch: {got_sha256}")
        got_manifest_digest = hashlib.sha384(data).digest()
        if got_manifest_digest != record["Digest"]:
            raise SystemExit(f"{component_name} BuildManifest sha2-384 digest mismatch")
        return data, record

    root_data, root_record = component(ROOT_COMPONENT, ROOT_PATH, EXPECTED_ROOT_SHA256)
    app_data, app_record = component(APP_COMPONENT, APP_PATH, EXPECTED_APP_SHA256)
    root_version, root_keys = parse_trustcache(root_data, ROOT_COMPONENT)
    app_version, app_keys = parse_trustcache(app_data, APP_COMPONENT)
    if len(root_keys) != EXPECTED_ROOT_COUNT or len(app_keys) != EXPECTED_APP_COUNT:
        raise SystemExit(f"entry-count mismatch: root={len(root_keys)}, app={len(app_keys)}")

    merged = sorted(set(root_keys) | set(app_keys))
    if len(merged) != len(root_keys) + len(app_keys) - len(set(root_keys) & set(app_keys)):
        raise SystemExit("merge count invariant failed")
    if merged != sorted(merged) or len(merged) != len(set(merged)):
        raise SystemExit("merged CDHash/type keys are not sorted and unique")
    if not set(root_keys).issubset(merged) or not set(app_keys).issubset(merged):
        raise SystemExit("merged table lost source trust-cache entries")
    unknown = b"\xff" * 21
    if unknown in merged or allow(merged, unknown):
        raise SystemExit("unknown CDHash/type unexpectedly allowed")
    if not all(allow(merged, key) for key in root_keys + app_keys):
        raise SystemExit("binary-search simulator rejected a pinned source entry")
    webbookmarks_arm64_key = WEBBOOKMARKS_ARM64_CDHASH + b"\x02"
    webbookmarks_arm64e_key = WEBBOOKMARKS_ARM64E_CDHASH + b"\x02"
    if webbookmarks_arm64_key not in app_keys or webbookmarks_arm64_key in root_keys:
        raise SystemExit("webbookmarksd arm64 hash is not App-only as expected")
    if webbookmarks_arm64e_key not in app_keys:
        raise SystemExit("webbookmarksd arm64e hash is missing from AppTrustCache")
    if not allow(merged, webbookmarks_arm64_key) or not allow(merged, webbookmarks_arm64e_key):
        raise SystemExit("binary-search simulator rejected webbookmarksd AppTrustCache hash")

    include = (
        "/* Exact iOS 16.7.16/20H392 OS StaticTrustCache + AppTrustCache entries. */\n"
        "/* Platform decision still requires the existing root mount/write gate. */\n"
        "static const unsigned char marble_ios16_cdhashes[][21] = {\n"
        + "".join("    {" + ",".join(f"0x{byte:02x}" for byte in key) + "},\n" for key in merged)
        + "};\n\n"
        "static bool\n"
        "marble_ios16_hash_allowed(const struct cs_blob *blob)\n"
        "{\n"
        "    if (blob == NULL || blob->csb_hashtype == NULL) return false;\n"
        "    unsigned char key[21];\n"
        "    memcpy(key, blob->csb_cdhash, CS_CDHASH_LEN);\n"
        "    key[20] = cs_hash_type(blob->csb_hashtype);\n"
        "    size_t lo = 0, hi = sizeof(marble_ios16_cdhashes)/sizeof(marble_ios16_cdhashes[0]);\n"
        "    while (lo < hi) {\n"
        "        size_t mid = lo+(hi-lo)/2;\n"
        "        int cmp = memcmp(key, marble_ios16_cdhashes[mid], sizeof(key));\n"
        "        if (cmp == 0) return true;\n"
        "        if (cmp < 0) hi = mid; else lo = mid+1;\n"
        "    }\n"
        "    return false;\n"
        "}\n"
    )
    STAGE.mkdir(parents=True, exist_ok=True)
    include_path = STAGE / "marble_ios16_cdhashes.inc"
    include_path.write_bytes(include.encode('utf-8'))
    manifest_out = {
        "source_ipsw": str(IPSW.relative_to(LAB)),
        "source_ipsw_size_bytes": IPSW.stat().st_size,
        "whole_ipsw_sha256_verified": False,
        "build_manifest": str(BUILD_MANIFEST.relative_to(LAB)),
        "build_manifest_sha256": build_manifest_sha,
        "product_version": manifest["ProductVersion"],
        "product_build": manifest["ProductBuildVersion"],
        "selected_identity": {"DeviceClass": identity["Info"]["DeviceClass"],
                               "Variant": identity["Info"]["Variant"]},
        "entries": {
            ROOT_COMPONENT: {"path": ROOT_PATH, "version": root_version,
                             "count": len(root_keys), "sha256": hashlib.sha256(root_data).hexdigest(),
                             "build_manifest_sha384": root_record["Digest"].hex(),
                             "hash_types": sorted({key[20] for key in root_keys})},
            APP_COMPONENT: {"path": APP_PATH, "version": app_version,
                            "count": len(app_keys), "sha256": hashlib.sha256(app_data).hexdigest(),
                            "build_manifest_sha384": app_record["Digest"].hex(),
                            "hash_types": sorted({key[20] for key in app_keys})},
        },
        "overlapping_cdhash_type_entries": len(set(root_keys) & set(app_keys)),
        "webbookmarksd": {
            "identifier": "com.apple.webbookmarksd",
            "arm64_cdhash": WEBBOOKMARKS_ARM64_CDHASH.hex(),
            "arm64_hash_type": 2,
            "arm64_in_app_trustcache": webbookmarks_arm64_key in app_keys,
            "arm64_in_root_trustcache": webbookmarks_arm64_key in root_keys,
            "arm64e_cdhash": WEBBOOKMARKS_ARM64E_CDHASH.hex(),
            "arm64e_hash_type": 2,
            "arm64e_in_app_trustcache": webbookmarks_arm64e_key in app_keys,
            "provenance": "Mac codesign -dvvv --arch arm64/arm64e against same 20H392 AppOS",
        },
        "merged_entry_count": len(merged),
        "merged_include_sha256": hashlib.sha256(include.encode()).hexdigest(),
        "policy": "existing AMFI signature path + existing root filesystem/writable-root predicate + exact 20-byte CDHash and hash-type membership; no path grants",
        "assertions": {"all_root_entries_retained": True, "all_app_entries_retained": True,
                       "sorted_unique_keys": True, "known_entries_accepted": True,
                       "unknown_ff_entry_rejected": True},
    }
    (STAGE / "manifest.json").write_text(json.dumps(manifest_out, indent=2) + "\n")
    print(json.dumps(manifest_out, indent=2))


if __name__ == "__main__":
    main()

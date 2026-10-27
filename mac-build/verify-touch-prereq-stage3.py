#!/usr/bin/env python3
"""Verify a Stage 3 package against its Stage 2 clock-probe predecessor.

This is a local artifact check only. It does not contact a Mac, device, or
network. The output verification.json is created only after all checks pass.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import struct
import sys
import uuid

ROOT = Path(__file__).resolve().parents[1]
STAGE2_DEFAULT = ROOT / "out" / "UNTESTED-marble8796-touch-clock-probe"
STAGE3_DEFAULT = ROOT / "out" / "UNTESTED-marble8796-touch-prereq-probe"
MAGIC = b"MARBLEXNUPAYLD1\0"
OWNER_DOMAIN = b"UniXNU.Marble.OwnerBootSet.v1\0"
OWNER_ADT_KEYS = {"boot-manifest-hash", "owner-boot-manifest-domain"}


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def sha(path: Path, algorithm: str = "sha256") -> str:
    digest = hashlib.new(algorithm)
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_json(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as stream:
        value = json.load(stream)
    require(isinstance(value, dict), f"{path.name} must contain a JSON object")
    return value


def codec_module():
    path = ROOT / "prepare-iphone16-qemu-adt.py"
    spec = importlib.util.spec_from_file_location("marble_stage3_adt_codec", path)
    require(spec is not None and spec.loader is not None, f"cannot load ADT codec: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def walk_nodes(node, path=()):
    props, children = node
    yield path, props
    for index, child in enumerate(children):
        yield from walk_nodes(child, path + (index,))


def compare_adt(stage2_data: bytes, stage3_data: bytes, codec) -> tuple[str, str, list[str]]:
    old, old_end = codec.read(stage2_data)
    new, new_end = codec.read(stage3_data)
    require(old_end == len(stage2_data) and new_end == len(stage3_data), "ADT has trailing or truncated bytes")
    old_nodes = list(walk_nodes(old))
    new_nodes = list(walk_nodes(new))
    require(len(old_nodes) == len(new_nodes), "ADT node count changed")
    random_seed_count = 0
    owner_hashes: list[str] = []
    preidentity_hashes: list[str] = []
    for (old_path, old_props), (new_path, new_props) in zip(old_nodes, new_nodes):
        require(old_path == new_path, "ADT node order/structure changed")
        is_chosen = new_props.get("name") == b"chosen\0"
        require(not (OWNER_ADT_KEYS & set(new_props)) or is_chosen,
                f"owner identity properties appeared outside /chosen at node {new_path}")
        require("random-seed" not in new_props or is_chosen,
                f"random-seed appeared outside /chosen at node {new_path}")
        require(set(old_props) - {"random-seed", *OWNER_ADT_KEYS} ==
                set(new_props) - {"random-seed", *OWNER_ADT_KEYS},
                f"ADT property set changed at node {old_path}")
        if is_chosen:
            for props in (old_props, new_props):
                require(set(props) & OWNER_ADT_KEYS == OWNER_ADT_KEYS,
                        f"owner identity properties are incomplete at node {old_path}")
                require(props["owner-boot-manifest-domain"] == OWNER_DOMAIN,
                        "ADT owner domain mismatch")
                require(len(props["boot-manifest-hash"]) == 48, "ADT owner manifest hash is not SHA-384")
                owner_hashes.append(props["boot-manifest-hash"].hex())
        else:
            require(not (set(old_props) | set(new_props)) & OWNER_ADT_KEYS,
                    f"owner identity properties outside /chosen at node {old_path}")
        if is_chosen:
            require("random-seed" in old_props and "random-seed" in new_props,
                    "random-seed presence changed")
            random_seed_count += 1
        else:
            require("random-seed" not in old_props, "random-seed appeared outside /chosen in Stage 2")
        for name in set(old_props) - {"random-seed", *OWNER_ADT_KEYS}:
            require(old_props[name] == new_props[name], f"ADT property changed: {name} at node {old_path}")
    require(len(owner_hashes) == 2, "owner fields did not occur exactly once per ADT")
    require(owner_hashes[0] != owner_hashes[1], "expected Stage 2 and Stage 3 owner hashes to differ")
    require(random_seed_count == 1, f"expected one changed random-seed property, found {random_seed_count}")
    # The packer hashes each ADT before adding the owner properties.
    for nodes in (old_nodes, new_nodes):
        for _, props in nodes:
            for name in OWNER_ADT_KEYS:
                props.pop(name, None)
        preidentity_hashes.append(hashlib.sha384(codec.encode(old if nodes is old_nodes else new)).hexdigest())
    # ADT comparison permits the freshly generated random seed, so the
    # pre-identity hashes are independently validated against each owner file.
    for _, props in new_nodes:
        for name in OWNER_ADT_KEYS:
            props.pop(name, None)
    stage3_preidentity = hashlib.sha384(codec.encode(new)).hexdigest()
    return preidentity_hashes[0], stage3_preidentity, owner_hashes


def descriptor_offset(firmware: bytes) -> int:
    require(firmware.count(MAGIC) == 1, "firmware payload descriptor magic is not unique")
    offset = firmware.index(MAGIC)
    ffs = offset - 28
    require(ffs >= 0, "firmware descriptor FFS header offset is invalid")
    expected_guid = uuid.UUID("5C9D5E94-47F5-4C61-AD6E-987C2420D91B").bytes_le
    require(firmware[ffs:ffs + 16] == expected_guid, "payload descriptor is not in expected firmware file")
    require(offset + 64 <= len(firmware), "firmware descriptor exceeds firmware bounds")
    return offset


def verify(stage2: Path, stage3: Path) -> dict:
    stage2 = stage2.resolve()
    stage3 = stage3.resolve()
    require(stage2.is_dir() and stage3.is_dir(), "both Stage 2 and Stage 3 package directories must exist")
    boot2, boot3 = load_json(stage2 / "boot.json"), load_json(stage3 / "boot.json")
    require(sha(stage2 / "marble8796-hfs-mount.img") == boot2.get("image_sha256"), "Stage 2 boot image SHA-256 mismatch")
    require(sha(stage3 / "marble8796-hfs-mount.img") == boot3.get("image_sha256"), "Stage 3 boot image SHA-256 mismatch")
    for label, folder, boot in (("Stage 2", stage2, boot2), ("Stage 3", stage3, boot3)):
        kernel = folder / "kernel.macho"
        roundtrip = folder / "roundtrip-kernel.macho"
        require(kernel.is_file() and roundtrip.is_file(), f"{label} kernel/roundtrip payload missing")
        require(kernel.read_bytes() == roundtrip.read_bytes(), f"{label} kernel FAT roundtrip mismatch")
        expected = boot.get("fixed_kernel_sha256")
        require(expected and sha(kernel) == expected, f"{label} kernel SHA-256 mismatch")
        adt = folder / "payload-stage/EFI/UniXNU/Payloads/kernel.macho.adt"
        adt_roundtrip = folder / "roundtrip-kernel.macho.adt"
        require(adt.is_file() and adt_roundtrip.is_file() and adt.read_bytes() == adt_roundtrip.read_bytes(),
                f"{label} ADT FAT roundtrip mismatch")
    require(boot3.get("source_kernel_sha256") == "0b6ca9d7110b3206310d26036ae90e3eb361e93447ce189abaf5b5c82e1398a7",
            "Stage 3 source kernel SHA-256 is not the reviewed build")
    require(boot2.get("kernel_va_base") == boot3.get("kernel_va_base"), "kernel VA base changed")
    cmd2, cmd3 = boot2.get("cmdline"), boot3.get("cmdline")
    require(isinstance(cmd2, str) and isinstance(cmd3, str), "boot cmdline missing")
    old_tokens, new_tokens = cmd2.split(), cmd3.split()
    old_modes = [i for i, token in enumerate(old_tokens) if token.startswith("marbletouchprobe=")]
    new_modes = [i for i, token in enumerate(new_tokens) if token.startswith("marbletouchprobe=")]
    require(len(old_modes) == len(new_modes) == 1, "expected exactly one touch probe mode in each cmdline")
    require(old_tokens[old_modes[0]] == "marbletouchprobe=2" and new_tokens[new_modes[0]] == "marbletouchprobe=3",
            "cmdline mode is not exactly 2 -> 3")
    old_tokens[old_modes[0]], new_tokens[new_modes[0]] = "marbletouchprobe=<mode>", "marbletouchprobe=<mode>"
    require(old_tokens == new_tokens, "cmdline changed beyond marbletouchprobe mode 2 -> 3")
    require(boot2.get("touch_probe_mode") == 2 and boot3.get("touch_probe_mode") == 3,
            "boot.json touch_probe_mode does not match package stage")
    require(boot3.get("readonly_touch_dma_prereq_snapshot") is True, "Stage 3 metadata does not enable read-only prerequisite snapshot")
    require(boot3.get("physical_touch_driver_enabled") is False, "Stage 3 claims physical touch driver enabled")

    codec = codec_module()
    adt2 = (stage2 / "payload-stage/EFI/UniXNU/Payloads/kernel.macho.adt").read_bytes()
    adt3 = (stage3 / "payload-stage/EFI/UniXNU/Payloads/kernel.macho.adt").read_bytes()
    preidentity_adt2_sha384, preidentity_adt3_sha384, adt_owner_hashes = compare_adt(adt2, adt3, codec)

    owner2 = load_json(stage2 / "owner-boot-identity.json")
    owner3 = load_json(stage3 / "owner-boot-identity.json")
    require(owner2.get("domain") == OWNER_DOMAIN[:-1].decode() and owner3.get("domain") == OWNER_DOMAIN[:-1].decode()
            and owner2.get("apple_personalized") is False and owner3.get("apple_personalized") is False,
            "owner identity domain/personalization metadata mismatch")
    kernel_sha384_2 = hashlib.sha384((stage2 / "kernel.macho").read_bytes()).hexdigest()
    kernel_sha384_3 = hashlib.sha384((stage3 / "kernel.macho").read_bytes()).hexdigest()
    firmware_path = stage3 / "SILICIUM_UEFI.fd"
    firmware3 = firmware_path.read_bytes()
    require(owner2.get("kernel_sha384") == kernel_sha384_2 and owner3.get("kernel_sha384") == kernel_sha384_3,
            "owner kernel SHA-384 mismatch")
    require(owner2.get("pre_identity_adt_sha384") == preidentity_adt2_sha384 and
            owner3.get("pre_identity_adt_sha384") == preidentity_adt3_sha384,
            "owner pre-identity ADT SHA-384 mismatch")
    require(owner2.get("firmware_sha384") == owner3.get("firmware_sha384"),
            "owner firmware SHA-384 changed between packages")
    require(owner2.get("cmdline") == cmd2 and owner3.get("cmdline") == cmd3,
            "owner identity cmdline mismatch")
    def owner_digest(owner: dict) -> str:
        owner_core = {key: value for key, value in owner.items() if key != "digest_sha384"}
        canonical = json.dumps(owner_core, sort_keys=True, separators=(",", ":")).encode()
        return hashlib.sha384(OWNER_DOMAIN + canonical).hexdigest()
    digest2, digest3 = owner_digest(owner2), owner_digest(owner3)
    require(owner2.get("digest_sha384") == digest2 and owner3.get("digest_sha384") == digest3,
            "owner identity digest does not recompute")
    require(adt_owner_hashes == [digest2, digest3], "owner identity digests do not match ADT")
    require(boot2.get("owner_boot_identity") == owner2 and boot3.get("owner_boot_identity") == owner3,
            "boot.json and owner identity file differ")

    fw2 = (stage2 / "SILICIUM_UEFI.fd").read_bytes()
    off2, off3 = descriptor_offset(fw2), descriptor_offset(firmware3)
    require(len(fw2) == len(firmware3) and off2 == off3, "firmware size or descriptor location changed")
    require(fw2[:off2] == firmware3[:off3] and fw2[off2 + 64:] == firmware3[off3 + 64:],
            "firmware differs outside the 64-byte payload descriptor")
    descriptor = struct.unpack_from("<16sQQIIQQQ", firmware3, off3)
    require(descriptor[0] == MAGIC, "Stage 3 firmware descriptor magic mismatch")
    fat = (stage3 / "payload-fat.img").read_bytes()
    import zlib
    require(descriptor[1] == 0 and descriptor[2] == len(fat) and descriptor[3] == (zlib.crc32(fat) & 0xffffffff)
            and descriptor[4] == 1 and descriptor[5:] == (19200000, 0, 0),
            "Stage 3 firmware descriptor does not describe its FAT payload")
    require(boot3.get("firmware_sha256") == hashlib.sha256(firmware3).hexdigest(), "Stage 3 firmware SHA-256 mismatch")
    return {
        "result": "PASS",
        "stage2": str(stage2),
        "stage3": str(stage3),
        "image_sha256": boot3["image_sha256"],
        "kernel_sha256": boot3["fixed_kernel_sha256"],
        "firmware_sha256": boot3["firmware_sha256"],
        "owner_digest_sha384": digest3,
        "pre_identity_adt_sha384": preidentity_adt3_sha384,
        "checks": [
            "Stage 2 and Stage 3 boot image hashes match boot.json",
            "kernel payload and FAT roundtrip match boot.json in both packages",
            "only cmdline change is marbletouchprobe=2 to marbletouchprobe=3",
            "ADT invariant except random-seed and per-package owner identity properties",
            "per-package owner kernel, pre-identity ADT and canonical digest recomputed; pre-descriptor firmware SHA-384 agrees",
            "firmware invariant except the validated 64-byte payload descriptor",
        ],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage2", type=Path, default=STAGE2_DEFAULT)
    parser.add_argument("--stage3", type=Path, default=STAGE3_DEFAULT)
    parser.add_argument("--output", type=Path, help="verification.json destination; defaults to Stage 3 package")
    args = parser.parse_args(argv)
    output = (args.output or args.stage3 / "verification.json").resolve()
    try:
        report = verify(args.stage2, args.stage3)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    except (OSError, ValueError, KeyError, struct.error, json.JSONDecodeError) as error:
        print(f"verification failed: {error}; no verification.json written", file=sys.stderr)
        return 1
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

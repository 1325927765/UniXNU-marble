#!/usr/bin/env python3
"""Check the built boot image against the exact shim, FD, DTB and ramdisk inputs."""
import hashlib
import json
import lzma
import struct
import sys
import tomllib
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def main():
    run = Path(sys.argv[1]).resolve()
    info = json.loads((run / "build-info.json").read_text())
    assert info["exit_code"] == 0, "Upstream build did not succeed"
    for name, pin in info["artifacts"].items():
        data = (run / name).read_bytes()
        assert len(data) == pin["bytes"], name
        assert hashlib.sha256(data).hexdigest() == pin["sha256"], name

    image = (run / "Mu-marble.img").read_bytes()
    fd = (run / "SILICIUM_UEFI.fd").read_bytes()
    shim = (run / "BootShim.bin").read_bytes()
    dtb = (run / "marble.dtb").read_bytes()
    ramdisk = (run / "ramdisk").read_bytes()
    config = tomllib.loads((ROOT / "sources/Mu-Silicium-marble/Resources/Configs/marble.toml").read_text())
    assert image[:8] == b"ANDROID!", "Android boot magic"
    kernel_size, ramdisk_size, os_version, header_size = struct.unpack_from("<4I", image, 8)
    header_version = struct.unpack_from("<I", image, 40)[0]
    assert header_version == config["boot_image"]["header_version"] == 4
    assert header_size == 1584
    signature_size = struct.unpack_from("<I", image, 1580)[0]
    # This pinned mkbootimg reserves a 4096-byte zero-filled GKI signature
    # when no signing key is given. It is a placeholder, not a valid signature.
    assert signature_size == 4096, "Unexpected GKI signature allocation"
    page = 4096
    kernel = image[page:page + kernel_size]
    ramdisk_offset = page + ((kernel_size + page - 1) // page) * page
    assert ramdisk_size == len(ramdisk)
    assert image[ramdisk_offset:ramdisk_offset + ramdisk_size] == ramdisk
    signature_offset = ramdisk_offset + ((ramdisk_size + page - 1) // page) * page
    assert image[signature_offset:] == bytes(signature_size)
    decoder = zlib.decompressobj(16 + zlib.MAX_WBITS)
    unpacked = decoder.decompress(kernel) + decoder.flush()
    assert decoder.eof, "Truncated gzip stream"
    assert unpacked == shim + fd, "BootShim / FD payload differs"
    assert decoder.unused_data == dtb, "Appended DTB differs"
    assert len(fd) == config["uefi_fd"]["size"] == 0x300000
    assert fd[40:44] == b"_FVH", "UEFI firmware volume signature"
    assert shim[56:60] == b"ARM\x64", "ARM64 Image header"
    assert struct.unpack_from("<QQ", shim, 8) == (config["uefi_fd"]["base"], len(fd))
    assert struct.unpack_from(">I", dtb, 0)[0] == 0xD00DFEED
    assert struct.unpack_from(">I", dtb, 4)[0] == len(dtb)

    menu_validation = None
    if info.get("includes_unixnu"):
        # Read the actual compressed FV_IMAGE from the final FD, rather than
        # trusting only the generated map or the presence of standalone EFIs.
        position = (struct.unpack_from("<H", fd, 48)[0] + 7) & ~7
        embedded = None
        while position + 24 <= len(fd) and fd[position:position+24] != bytes([255]) * 24:
            file_size = int.from_bytes(fd[position+20:position+23], "little")
            assert 24 <= file_size <= len(fd) - position
            if fd[position+18] == 0x0B:  # EFI_FV_FILETYPE_FIRMWARE_VOLUME_IMAGE
                body = fd[position+24:position+file_size]
                section_size = int.from_bytes(body[:3], "little")
                assert body[3] == 0x02  # EFI_SECTION_GUID_DEFINED
                data_offset = struct.unpack_from("<H", body, 20)[0]
                embedded = lzma.decompress(body[data_offset:section_size])
                break
            position = (position + file_size + 7) & ~7
        assert embedded is not None, "No compressed inner firmware volume"
        modules = {}
        names = ("UniXNU.efi", "UniXNUDxe.efi") + (("DarwinBoot.efi", "MarbleDarwinBootProbe.efi") if info.get("includes_darwinboot") else ())
        if info.get("includes_early_payload_transport"):
            names += ("MarblePayloadBoot.efi",)
        for name in names:
            module = (run / name).read_bytes()
            pe_offset = struct.unpack_from("<I", module, 60)[0]
            assert module[:2] == b"MZ" and module[pe_offset:pe_offset+4] == b"PE\0\0"
            assert struct.unpack_from("<H", module, pe_offset+4)[0] == 0xAA64
            offset = embedded.find(module)
            assert offset >= 0, f"{name} not present byte-for-byte inside final FD"
            modules[name] = {"machine": "AARCH64", "offset_in_decompressed_section": offset}
        if info.get("includes_early_payload_transport"):
            assert (run / "MarblePayloadFixture.efi").read_bytes() not in embedded, "QEMU fixture leaked into phone FD"
        values = {}
        for line in (run / "FVMAIN_COMPACT.Fv.txt").read_text().splitlines():
            if line.startswith("EFI_FV_"):
                key, value = line.split("=")
                values[key.strip()] = int(value.strip(), 16)
        assert values["EFI_FV_TOTAL_SIZE"] == len(fd)
        assert values["EFI_FV_TAKEN_SIZE"] < len(fd)
        menu_validation = {"modules": modules, "compressed_fv_free_bytes": len(fd) - values["EFI_FV_TAKEN_SIZE"]}

    report = {
        "result": "PASS",
        "run": str(run),
        "checks": [
            "Build succeeded and preserved artifact hashes match",
            "Android v4 header, lengths, offsets and page alignment match",
            "Gzip decompresses exactly to BootShim + firmware volume",
            "Appended DTB and packaged ramdisk match inputs byte for byte",
            "Firmware volume is 3 MiB with valid FV signature",
            "BootShim has ARM64 header; DTB has valid header and total length",
        ],
        "kernel_size": kernel_size,
        "ramdisk_size": ramdisk_size,
        "fd_base_from_source": hex(config["uefi_fd"]["base"]),
        "fd_size": len(fd),
        "image_size": len(image),
        "gki_signature": "4096-byte zero placeholder; not signed",
        "ramdisk_role": "Original upstream placeholder, not an Android userspace ramdisk",
        "hardware_boot_tested": False,
        "includes_unixnu": bool(info.get("includes_unixnu")),
        "includes_darwinboot": bool(info.get("includes_darwinboot")),
        "menu_integration": menu_validation,
        "includes_xnu_or_ios": False,
        "scope": "Static container/input integrity only; no hardware compatibility claim",
    }
    (run / "validation.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()

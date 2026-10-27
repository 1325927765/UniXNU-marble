#!/usr/bin/env python3
"""Add the pinned UniXNU menu to the pinned marble firmware, without changing its memory map."""
import hashlib
import argparse
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent
UEFI = ROOT / "sources/Mu-Silicium-marble"
UNIXNU = ROOT / "sources/UniXNU"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--darwinboot-probe", action="store_true")
    args = parser.parse_args()
    pins = json.loads((ROOT / "sources.lock.json").read_text())["sources"]
    for name, path in (("Mu-Silicium-marble", UEFI), ("UniXNU", UNIXNU)):
        actual = subprocess.check_output(["git", "-C", str(path), "rev-parse", "HEAD"], text=True).strip()
        assert actual == pins[name]["commit"], name
    board = "Platforms/Xiaomi/marblePkg/"
    prefix = "darwinboot" if args.darwinboot_probe else "menu"
    recognized = {}
    for name in ("menu", "darwinboot", "early"):
        path = ROOT / f"research/{name}-integration-inputs.json"
        if path.is_file():
            for relative, digest in json.loads(path.read_text()).items():
                recognized.setdefault(relative, set()).add(digest)
    changes = {
        board + "marble.dsc": lambda text: text + "\r\n!include marblePkg/Include/UniXNU.dsc.inc\r\n",
        board + "marble.fdf": lambda text: text.replace("  !include Include/DXE.inc", "  !include Include/DXE.inc\r\n  !include Include/UniXNU.fdf.inc"),
        board + "Include/APRIORI.inc": lambda text: text.replace("  INF MdeModulePkg/Universal/BdsDxe/BdsDxe.inf", "  # Register the FV application before BDS enumerates boot options.\r\n  INF UniXNUPkg/Driver/UniXNUDxe/UniXNUDxe.inf\r\n  INF MdeModulePkg/Universal/BdsDxe/BdsDxe.inf"),
        board + "DeviceBuild.py": lambda text: text.replace('        "Platforms/Xiaomi",', '        "Platforms/Xiaomi",\r\n        str(Path(WorkspaceRoot).parent / "UniXNU" / "package"),'),
    }
    if args.darwinboot_probe:
        darwin = UNIXNU / "drivers/DarwinBoot"
        pin = subprocess.check_output(["git", "-C", str(UNIXNU), "ls-tree", "HEAD", "drivers/DarwinBoot"], text=True).split()[2]
        actual = subprocess.check_output(["git", "-C", str(darwin), "rev-parse", "HEAD"], text=True).strip()
        assert actual == pin
        changes[board + "DeviceBuild.py"] = lambda text: text.replace('        "Platforms/Xiaomi",', '        "Platforms/Xiaomi",\r\n        str(Path(WorkspaceRoot).parent / "UniXNU" / "package"),\r\n        str(Path(WorkspaceRoot).parent / "UniXNU" / "drivers" / "DarwinBoot"),')
        changes[board + "Include/APRIORI.inc"] = lambda text: text.replace("  INF MdeModulePkg/Universal/BdsDxe/BdsDxe.inf", "  # Loader and firmware application registration before BDS.\r\n  INF DarwinBootPkg/Driver/DarwinBoot.inf\r\n  INF UniXNUPkg/Driver/UniXNUDxe/UniXNUDxe.inf\r\n  INF MdeModulePkg/Universal/BdsDxe/BdsDxe.inf")
    for relative, transform in changes.items():
        original = subprocess.check_output(["git", "-C", str(UEFI), "show", "HEAD:" + relative])
        updated = transform(original.decode()).encode()
        assert updated != original, relative
        path = UEFI / relative
        if path.read_bytes() not in (original, updated) and hashlib.sha256(path.read_bytes()).hexdigest() not in recognized.get(relative, set()):
            raise RuntimeError(f"Unexpected local edits: {relative}")
        path.write_bytes(updated)

    generated = {
        board + "Include/UniXNU.dsc.inc": """# UniXNU menu integration; upstream libraries remain unchanged.
[LibraryClasses]
  UniXNULib|UniXNUPkg/Library/UniXNULib/UniXNULib.inf

[Components]
  UniXNUPkg/Application/UniXNU/UniXNU.inf
  UniXNUPkg/Driver/UniXNUDxe/UniXNUDxe.inf
""",
        board + "Include/UniXNU.fdf.inc": """# Application and registrar must be in the same firmware volume.
  INF UniXNUPkg/Application/UniXNU/UniXNU.inf
  INF UniXNUPkg/Driver/UniXNUDxe/UniXNUDxe.inf
""",
    }
    if args.darwinboot_probe:
        generated[board + "Include/UniXNU.dsc.inc"] += """
[PcdsFixedAtBuild]
  gUniXNUPkgTokenSpaceGuid.PcdUniXNUApplicationFile|{ GUID(\"A8763D2E-EE65-4FD2-810A-63AD45E218B0\") }

[Components]
  DarwinBootPkg/Driver/DarwinBoot.inf
  marblePkg/Applications/DarwinBootProbe/Probe.inf
  Test/Validation.inf
"""
        generated[board + "Include/UniXNU.fdf.inc"] += "  INF DarwinBootPkg/Driver/DarwinBoot.inf\n  INF marblePkg/Applications/DarwinBootProbe/Probe.inf\n"
        for name in ("Probe.inf", "Probe.c"):
            generated[board + "Applications/DarwinBootProbe/" + name] = (ROOT / "device/probe" / name).read_text()
    for relative, text in generated.items():
        path = UEFI / relative
        if path.exists() and path.read_bytes() != text.encode() and hashlib.sha256(path.read_bytes()).hexdigest() not in recognized.get(relative, set()):
            raise RuntimeError(f"Unexpected local file: {relative}")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    manifest = {relative: hashlib.sha256((UEFI / relative).read_bytes()).hexdigest() for relative in (*changes, *generated)}
    (ROOT / f"research/{prefix}-integration-inputs.json").write_text(json.dumps(manifest, indent=2) + "\n")
    diff = subprocess.check_output(["git", "-C", str(UEFI), "diff", "--", *changes])
    (ROOT / f"research/{prefix}-integration.patch").write_bytes(diff)
    print(f"{prefix} integration applied; no board memory/image parameters changed.")


if __name__ == "__main__":
    main()

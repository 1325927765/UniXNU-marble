#!/usr/bin/env python3
"""Run the pinned marble UEFI's own build script and preserve logs and artifacts."""
import datetime
import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SOURCE = ROOT / "sources/Mu-Silicium-marble"


def capture(*args):
    result = subprocess.run(args, cwd=SOURCE, capture_output=True, text=True)
    if result.returncode:
        raise RuntimeError(result.stderr)
    return result.stdout.strip()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--unixnu-menu", action="store_true", help="Build the local UniXNU menu integration instead of the original baseline")
    parser.add_argument("--darwinboot-probe", action="store_true", help="Build the DarwinBoot integration and diagnostic wrapper")
    parser.add_argument("--early-xnu", action="store_true", help="Build the real XNU payload transport application")
    args = parser.parse_args()
    if args.early_xnu:
        args.darwinboot_probe = True
    if args.darwinboot_probe:
        args.unixnu_menu = True
    if sys.platform != "linux":
        raise SystemExit("Run this script inside the WSL research workspace.")
    pin = json.loads((ROOT / "sources.lock.json").read_text())["sources"]["Mu-Silicium-marble"]["commit"]
    if capture("git", "rev-parse", "HEAD") != pin:
        raise SystemExit("UEFI checkout does not match sources.lock.json")
    changes = set(capture("git", "diff", "--name-only", "HEAD").splitlines())
    if not args.unixnu_menu and changes - {"Mu_Basecore"}:
        raise SystemExit("UEFI has local integration changes; use --unixnu-menu or restore the baseline first.")
    if args.unixnu_menu:
        prefix = "early" if args.early_xnu else ("darwinboot" if args.darwinboot_probe else "menu")
        manifest = json.loads((ROOT / f"research/{prefix}-integration-inputs.json").read_text())
        for relative, digest in manifest.items():
            assert hashlib.sha256((SOURCE / relative).read_bytes()).hexdigest() == digest, relative
        unixnu_pin = json.loads((ROOT / "sources.lock.json").read_text())["sources"]["UniXNU"]["commit"]
        assert capture("git", "-C", str(ROOT / "sources/UniXNU"), "rev-parse", "HEAD") == unixnu_pin
        if args.darwinboot_probe:
            darwinboot_pin = capture("git", "-C", str(ROOT / "sources/UniXNU"), "ls-tree", "HEAD", "drivers/DarwinBoot").split()[2]
            assert capture("git", "-C", str(ROOT / "sources/UniXNU/drivers/DarwinBoot"), "rev-parse", "HEAD") == darwinboot_pin
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    suffix = "-early-xnu" if args.early_xnu else ("-darwinboot-probe" if args.darwinboot_probe else ("-unixnu-menu" if args.unixnu_menu else ""))
    run = ROOT / "build-runs" / (stamp + suffix)
    run.mkdir(parents=True, exist_ok=False)
    python = ROOT / ".venv/bin/python"
    if not python.is_file():
        raise SystemExit("Create the local venv and install pip-requirements.txt first.")
    env = dict(os.environ)
    env["PATH"] = str(python.parent) + os.pathsep + env.get("PATH", "")
    env["CLANGPDB_AARCH64_PREFIX"] = "aarch64-linux-gnu-"
    env["GCC5_AARCH64_PREFIX"] = "aarch64-linux-gnu-"
    env["PYTHONUNBUFFERED"] = "1"
    # Keep parallel compilation within a reasonable memory budget on this host.
    env["MAX_CONCURRENT_THREAD_NUMBER"] = str(min(8, os.cpu_count() or 2))
    command = [str(python), "build_uefi.py", "-d", "marble", "-r", "RELEASE"]
    metadata = {
        "command": command,
        "commit": pin,
        "started_utc": stamp,
        "submodules_before": capture("git", "submodule", "status", "--recursive").splitlines(),
        "source_changes_before": capture("git", "status", "--short"),
        "python_dependencies": capture(str(python), "-m", "pip", "freeze").splitlines(),
        "hardware_tested": False,
        "includes_unixnu": args.unixnu_menu,
        "includes_darwinboot": args.darwinboot_probe,
        "includes_early_payload_transport": args.early_xnu,
        "darwinboot_commit": darwinboot_pin if args.darwinboot_probe else None,
        "unixnu_commit": unixnu_pin if args.unixnu_menu else None,
        "integration_inputs": manifest if args.unixnu_menu else None,
    }
    (run / "build-info.json").write_text(json.dumps(metadata, indent=2) + "\n")
    print(f"Build log: {run / 'build.log'}", flush=True)
    with (run / "build.log").open("w") as log:
        result = subprocess.run(command, cwd=SOURCE, env=env, stdout=log, stderr=subprocess.STDOUT)
    metadata["exit_code"] = result.returncode
    metadata["source_changes_after"] = capture("git", "status", "--short")
    metadata["artifacts"] = {}
    if result.returncode == 0:
        for relative in (
            "Mu-marble.img",
            "Build/marblePkg/RELEASE_CLANGPDB/FV/SILICIUM_UEFI.fd",
            "BootShim/BootShim.bin",
            "Resources/DTBs/marble.dtb",
            "Resources/ramdisk",
        ):
            path = SOURCE / relative
            if not path.is_file():
                raise RuntimeError(f"Build reported success but output is absent: {relative}")
            destination = run / path.name
            shutil.copy2(path, destination)
            metadata["artifacts"][destination.name] = {
                "bytes": destination.stat().st_size,
                "sha256": hashlib.sha256(destination.read_bytes()).hexdigest(),
            }
        if args.unixnu_menu:
            names = ("UniXNU.efi", "UniXNUDxe.efi") + (("DarwinBoot.efi", "MarbleDarwinBootProbe.efi", "DarwinBootValidation.efi") if args.darwinboot_probe else ())
            if args.early_xnu:
                names += ("MarblePayloadBoot.efi", "MarblePayloadFixture.efi")
            for name in names:
                path = SOURCE / "Build/marblePkg/RELEASE_CLANGPDB/AARCH64" / name
                shutil.copy2(path, run / name)
                metadata["artifacts"][name] = {"bytes": path.stat().st_size, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
            for name in ("FVMAIN.Fv.txt", "FVMAIN_COMPACT.Fv.txt", "FVMAIN.Fv.map"):
                shutil.copy2(SOURCE / "Build/marblePkg/RELEASE_CLANGPDB/FV" / name, run / name)
    (run / "build-info.json").write_text(json.dumps(metadata, indent=2) + "\n")
    print(json.dumps({"run": str(run), "exit_code": result.returncode, "artifacts": metadata["artifacts"]}, indent=2))
    return result.returncode


if __name__ == "__main__":
    sys.exit(main())

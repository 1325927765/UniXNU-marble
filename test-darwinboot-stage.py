#!/usr/bin/env python3
"""Exercise the exact embedded DarwinBoot and board probe under QEMU, not marble hardware."""
import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
UPSTREAM = ROOT / "sources/UniXNU"


def main():
    run = Path(sys.argv[1]).resolve()
    runner = UPSTREAM / "package/Scripts/qemu-run.py"
    python = str(ROOT / ".venv/bin/python")
    results = {}
    # Upstream's synthetic Mach-O is a QEMU-only ABI test, not XNU, and is
    # deliberately kept outside the device output directory.
    esp = run / "qemu-handoff-esp"
    payload = esp / "EFI/UniXNU/Payloads"
    payload.mkdir(parents=True, exist_ok=True)
    subprocess.run([python, str(UPSTREAM / "drivers/DarwinBoot/Test/make-fixtures.py"), str(payload), "--gop"], check=True)
    (esp / "EFI/BOOT").mkdir(exist_ok=True)
    shutil.copy2(run / "UniXNU.efi", esp / "EFI/BOOT/BOOTAA64.EFI")
    for name in ("DarwinBoot.efi", "DarwinBootValidation.efi"):
        shutil.copy2(run / name, payload / name)
    (esp / "EFI/UniXNU/unixnu.toml").write_text('''version = 1
[boot]
timeout = 1
default = "synthetic"
[kits]
autoload = false
[[driver]]
path = "Payloads/DarwinBoot.efi"
[[driver]]
path = "Payloads/DarwinBootValidation.efi"
[[entry]]
id = "synthetic"
title = "QEMU synthetic ABI test (not XNU)"
type = "xnu"
path = "Payloads/kernel.macho"
args = "darwinboot.fixture=1"
initrd = "Payloads/ramdisk.bin"
''')
    expectations = [
        "DARWINBOOT: loader v2 installed EL1",
        "DARWINBOOT-VALIDATION: 33 rejected requests; firmware retained PASS",
        "DARWINBOOT-VIDEO-VALIDATION: 8 malformed/unsupported GOP field sets refused PASS",
        "DARWINBOOT: inputs validated; exiting boot services",
        "DARWINBOOT-FIXTURE: actual GOP boot video after ExitBootServices PASS",
    ]
    command = [python, str(runner), str(esp), "--log", str(run / "qemu-handoff.log"), "--cpus", "1", "--timeout", "40", "--finish-on-expect"]
    for pattern in expectations:
        command += ["--expect", pattern]
    command += ["--reject", "DARWINBOOT[^\\n]*FAIL", "--reject", "ASSERT"]
    with (run / "qemu-handoff-test.txt").open("w") as log:
        result = subprocess.run(command, stdout=log, stderr=subprocess.STDOUT)
    results["synthetic_handoff"] = "PASS" if result.returncode == 0 else "FAIL"
    print((run / "qemu-handoff-test.txt").read_text(), flush=True)
    if result.returncode:
        raise SystemExit(result.returncode)

    esp = run / "qemu-probe-esp"
    payload = esp / "EFI/UniXNU/Payloads"
    payload.mkdir(parents=True, exist_ok=True)
    (esp / "EFI/BOOT").mkdir(exist_ok=True)
    shutil.copy2(run / "UniXNU.efi", esp / "EFI/BOOT/BOOTAA64.EFI")
    for name in ("DarwinBoot.efi", "MarbleDarwinBootProbe.efi"):
        shutil.copy2(run / name, payload / name)
    (esp / "EFI/UniXNU/unixnu.toml").write_text('''version = 1
[boot]
timeout = 1
default = "probe"
[kits]
autoload = false
[[driver]]
path = "Payloads/DarwinBoot.efi"
[[entry]]
id = "probe"
title = "DarwinBoot diagnostic"
type = "efi"
path = "Payloads/MarbleDarwinBootProbe.efi"
''')
    command = [python, str(runner), str(esp), "--log", str(run / "qemu-probe.log"), "--screenshot", str(run / "qemu-probe.png"),
               "--cpus", "1", "--timeout", "35", "--finish-on-expect", "--menu-marker", "MARBLE-PROBE: waiting for key", "--keys", "up",
               "--expect", "MARBLE-PROBE: loader checks PASS", "--expect", "MARBLE-PROBE: waiting for key", "--expect", "UNIXNU: menu: shown",
               "--reject", "MARBLE-PROBE: loader checks FAIL", "--reject", "ASSERT"]
    with (run / "qemu-probe-test.txt").open("w") as log:
        result = subprocess.run(command, stdout=log, stderr=subprocess.STDOUT)
    print((run / "qemu-probe-test.txt").read_text(), flush=True)
    clean = (run / "qemu-probe.clean.log").read_text()
    returned = clean.find("MARBLE-PROBE: waiting for key") < clean.rfind("UNIXNU: menu: shown")
    results["probe_and_return_to_menu"] = "PASS" if result.returncode == 0 and returned else "FAIL"
    report = {"machine": "QEMU AArch64 virt / AAVMF", "tests": results, "marble_hardware_tested": False, "xnu_executed": False,
              "synthetic_payload_distributed_to_phone": False, "scope": "Exact embedded EFI modules; synthetic handoff is an upstream ABI fixture, not XNU"}
    (run / "qemu-result.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))
    if result.returncode or not returned:
        raise SystemExit(1)


if __name__ == "__main__":
    main()

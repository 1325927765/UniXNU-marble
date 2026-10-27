#!/usr/bin/env python3
"""Collect bounded, read-only Marble SPI/controller state through ADB."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import sys
import threading
from typing import Callable

PER_COMMAND_CAP = 128 * 1024
TOTAL_CAP = 2 * 1024 * 1024
TIMEOUT_SECONDS = 15
PROPERTIES = ("ro.product.device", "ro.build.product", "ro.product.vendor.device",
              "ro.product.model", "ro.bootmode")

SPI_READ = """d=/sys/bus/spi/devices/spi0.0
if [ ! -e \"$d\" ]; then echo 'spi0.0: absent'; exit 0; fi
echo \"device=$d\"
for f in modalias uevent; do
  if [ -r \"$d/$f\" ]; then echo \"[$f]\"; cat \"$d/$f\" 2>&1
  elif [ -e \"$d/$f\" ]; then echo \"[$f: permission denied or unreadable]\"
  else echo \"[$f: absent]\"; fi
done
for f in driver of_node; do
  if [ -L \"$d/$f\" ]; then echo \"[$f]\"; readlink -f \"$d/$f\" 2>&1
  elif [ -e \"$d/$f\" ]; then echo \"[$f: present, not a symlink]\"
  else echo \"[$f: absent]\"; fi
done
f=\"$d/power/runtime_status\"
if [ -r \"$f\" ]; then echo '[runtime_status]'; cat \"$f\" 2>&1
elif [ -e \"$f\" ]; then echo '[runtime_status: permission denied or unreadable]'
else echo '[runtime_status: absent]'; fi"""

DEBUGFS_READ = """for f in /sys/kernel/debug/clk/clk_summary /sys/kernel/debug/regulator/regulator_summary; do
 if [ -r \"$f\" ]; then echo \"[$f]\"; cat \"$f\" 2>&1
 elif [ -e \"$f\" ]; then echo \"[$f: permission denied or unreadable]\"
 else echo \"[$f: absent]\"; fi
done
found=0
for d in /sys/kernel/debug/pinctrl/*; do
 [ -d \"$d\" ] || continue
 found=1
 for n in pinmux-pins pinconf-pins; do
  f=\"$d/$n\"
  if [ -r \"$f\" ]; then
   echo \"[$f GPIO16..21]\"
   grep -E '[gG][pP][iI][oO][-_ ]?(1[6-9]|2[01])([^0-9]|$)' \"$f\" 2>&1 || true
  elif [ -e \"$f\" ]; then echo \"[$f: permission denied or unreadable]\"
  else echo \"[$f: absent]\"
  fi
 done
done
if [ \"$found\" -eq 0 ]; then echo '[pinctrl: absent or inaccessible]'; fi"""


DMA_BINDINGS_READ = """found=0
for d in /sys/bus/platform/devices/900000.* /sys/bus/platform/devices/9c0000.* /sys/bus/platform/devices/990000.*; do
 [ -d \"$d\" ] || continue
 found=1
 echo \"[platform $d]\"
 for n in driver of_node iommu_group; do
  p=\"$d/$n\"
  if [ -L \"$p\" ]; then
   target=$(readlink -f \"$p\" 2>&1)
   echo \"$n -> $target\"
   if [ \"$n\" = iommu_group ]; then
    case \"$target\" in
     /sys/kernel/iommu_groups/*)
      if [ -d \"$target\" ]; then
       for a in type reserved_regions; do
        f=\"$target/$a\"
        if [ -r \"$f\" ]; then echo \"[$f]\"; cat \"$f\" 2>&1
        elif [ -e \"$f\" ]; then echo \"[$f: permission denied or unreadable]\"
        else echo \"[$f: absent]\"; fi
       done
       devdir=\"$target/devices\"
       if [ -d \"$devdir\" ]; then
        for link in \"$devdir\"/*; do
         [ -L \"$link\" ] || continue
         echo \"iommu-device $(basename \"$link\") -> $(readlink -f \"$link\" 2>&1)\"
        done
       else echo \"[$devdir: absent]\"; fi
      fi ;;
     *) echo 'iommu_group target outside /sys/kernel/iommu_groups; not inspected' ;;
    esac
   fi
  elif [ -e \"$p\" ]; then echo \"$n: present, not a symlink\"
  else echo \"$n: absent\"; fi
 done
 for n in power/runtime_status coherent_dma_mask dma_mask_bits; do
  f=\"$d/$n\"
  if [ -r \"$f\" ]; then echo \"[$f]\"; cat \"$f\" 2>&1
  elif [ -e \"$f\" ]; then echo \"[$f: permission denied or unreadable]\"
  else echo \"[$f: absent]\"; fi
 done
done
if [ \"$found\" -eq 0 ]; then echo '[target platform devices: absent]'; fi
for p in /sys/kernel/debug/iommu /sys/kernel/debug/arm-smmu /sys/kernel/debug/arm_smmu /sys/kernel/debug/gpi-dma /sys/kernel/debug/qcom_gpi /sys/kernel/debug/dmaengine; do
 if [ -e \"$p\" ]; then
  ls -ld \"$p\" 2>&1
  if [ -d \"$p\" ]; then
   for c in \"$p\"/*; do [ -e \"$c\" ] || continue; basename \"$c\"; done
  fi
 else echo \"$p: absent\"; fi
done"""
class CollectionError(RuntimeError):
    pass


def run_bounded(argv: list[str], *, timeout: int = TIMEOUT_SECONDS,
                cap: int = PER_COMMAND_CAP) -> dict:
    """Drain process pipes while enforcing output and time bounds."""
    proc = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    assert proc.stdout is not None and proc.stderr is not None
    lock = threading.Lock()
    overflow = threading.Event()
    chunks = {"stdout": bytearray(), "stderr": bytearray()}
    total = 0

    def drain(name: str, stream) -> None:
        nonlocal total
        while True:
            data = stream.read(4096)
            if not data:
                return
            with lock:
                room = cap - total
                if len(data) > room:
                    if room > 0:
                        chunks[name].extend(data[:room])
                        total += room
                    overflow.set()
                    try:
                        proc.kill()
                    except OSError:
                        pass
                    continue
                chunks[name].extend(data)
                total += len(data)

    threads = [threading.Thread(target=drain, args=(name, stream), daemon=True)
               for name, stream in (("stdout", proc.stdout), ("stderr", proc.stderr))]
    for thread in threads:
        thread.start()
    try:
        proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        proc.kill()
        proc.wait()
        for thread in threads:
            thread.join()
        proc.stdout.close()
        proc.stderr.close()
        raise CollectionError(f"command timed out after {timeout}s") from exc
    for thread in threads:
        thread.join()
    proc.stdout.close()
    proc.stderr.close()
    if overflow.is_set():
        raise CollectionError(f"command output exceeded {cap} byte cap")
    return {"returncode": proc.returncode,
            "stdout": chunks["stdout"].decode("utf-8", "replace"),
            "stderr": chunks["stderr"].decode("utf-8", "replace"),
            "bytes": total}


def adb_argv(adb_path: str, serial: str, *args: str) -> list[str]:
    return [adb_path, "-s", serial, *args]


def shell_argv(adb_path: str, serial: str, script: str) -> list[str]:
    # ADB joins remote argv into shell text rather than preserving POSIX argv.
    # Pass one complete fixed script; an unquoted nested `sh -c` loses its
    # command-string boundary and can silently misparse property reads.
    return adb_argv(adb_path, serial, "shell", script)


def property_script() -> str:
    return "printf '%s\\n' " + " ".join('"$(getprop ' + key + ')"' for key in PROPERTIES)


def collect(adb_path: str, serial: str, out: Path,
            runner: Callable[..., dict] = run_bounded) -> dict:
    out = out.expanduser().resolve()
    if out.exists():
        raise CollectionError(f"refusing to overwrite existing output path: {out}")
    if not out.parent.is_dir():
        raise CollectionError(f"output parent directory does not exist: {out.parent}")
    used = 0

    def execute(argv: list[str]) -> dict:
        nonlocal used
        remaining = TOTAL_CAP - used
        if remaining <= 0:
            raise CollectionError(f"total output exceeded {TOTAL_CAP} byte cap")
        result = runner(argv, timeout=TIMEOUT_SECONDS,
                        cap=min(PER_COMMAND_CAP, remaining))
        command_cap = min(PER_COMMAND_CAP, remaining)
        if result["bytes"] < 0:
            raise CollectionError("runner returned an invalid negative byte count")
        if result["bytes"] > command_cap:
            raise CollectionError(f"command output exceeded {command_cap} byte cap")
        used += result["bytes"]
        if used > TOTAL_CAP:
            raise CollectionError(f"total output exceeded {TOTAL_CAP} byte cap")
        return result

    state_result = execute(adb_argv(adb_path, serial, "get-state"))
    state = state_result["stdout"].strip()
    if state_result["returncode"] != 0 or state not in ("device", "recovery"):
        raise CollectionError(f"ADB target state is {state!r}; expected device or recovery")
    prop_result = execute(shell_argv(adb_path, serial, property_script()))
    if prop_result["returncode"] != 0:
        raise CollectionError("could not read product identity properties")
    props = dict(zip(PROPERTIES, prop_result["stdout"].splitlines()))
    products = [props.get(key, "").strip().lower() for key in PROPERTIES[:3]
                if props.get(key, "").strip().lower() not in ("", "unknown")]
    if not products or any(v not in ("marble", "marblein") for v in products):
        raise CollectionError(f"product identity is absent or not Marble: {props}")

    evidence = {"serial": serial, "adb_state": state, "properties": props,
                "product_verified": True,
                "collection": "fixed read-only ADB shell reads; no SPI transaction or device state change",
                "limits": {"per_command_bytes": PER_COMMAND_CAP,
                           "total_bytes": TOTAL_CAP, "timeout_seconds": TIMEOUT_SECONDS}}
    spi = execute(shell_argv(adb_path, serial, SPI_READ))
    debug = execute(shell_argv(adb_path, serial, DEBUGFS_READ))
    dma = execute(shell_argv(adb_path, serial, DMA_BINDINGS_READ))
    evidence["spi0_0"] = {"stdout": spi["stdout"], "stderr": spi["stderr"],
                          "returncode": spi["returncode"], "captured_bytes": spi["bytes"]}
    evidence["debug_state"] = {"stdout": debug["stdout"], "stderr": debug["stderr"],
                               "returncode": debug["returncode"], "captured_bytes": debug["bytes"]}
    evidence["dma_bindings"] = {"stdout": dma["stdout"], "stderr": dma["stderr"],
                                "returncode": dma["returncode"], "captured_bytes": dma["bytes"]}
    try:
        with out.open("x", encoding="utf-8") as stream:
            stream.write(json.dumps(evidence, indent=2) + "\n")
    except FileExistsError as exc:
        raise CollectionError(f"refusing to overwrite existing output path: {out}") from exc
    return evidence


def command_plan(adb_path: str, serial: str) -> list[list[str]]:
    return [adb_argv(adb_path, serial, "get-state"),
            shell_argv(adb_path, serial, property_script()),
            shell_argv(adb_path, serial, SPI_READ),
            shell_argv(adb_path, serial, DEBUGFS_READ),
            shell_argv(adb_path, serial, DMA_BINDINGS_READ)]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--adb", required=True, help="explicit adb executable path")
    parser.add_argument("--serial", required=True, help="explicit ADB serial")
    parser.add_argument("--out", required=True, type=Path,
                        help="new host JSON file; existing files are never overwritten")
    parser.add_argument("--list-commands", action="store_true",
                        help="print fixed command plan without running ADB")
    args = parser.parse_args(argv)
    if args.list_commands:
        print(json.dumps(command_plan(args.adb, args.serial), indent=2))
        return 0
    try:
        evidence = collect(args.adb, args.serial, args.out)
    except (CollectionError, OSError) as exc:
        print(f"collection refused/failed: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(evidence, indent=2))
    print(f"Report: {args.out.expanduser().resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())



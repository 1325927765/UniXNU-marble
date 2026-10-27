#!/usr/bin/env python3
"""Read-only local inventory. No downloads, firmware execution or phone access."""
import hashlib
import json
import platform
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent
LOCK = json.loads((ROOT / "sources.lock.json").read_text(encoding="utf-8"))


def git(path, *args):
    result = subprocess.run(["git", "-C", str(path), *args], capture_output=True, text=True)
    return result.stdout.strip() if result.returncode == 0 else None


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None


def main():
    sources = {}
    for name, pin in LOCK["sources"].items():
        path = ROOT / "sources" / name
        actual = git(path, "rev-parse", "HEAD") if path.is_dir() else None
        submodules = git(path, "submodule", "status") if actual else None
        changes = git(path, "diff", "--name-only", "HEAD") if actual else None
        sources[name] = {
            "commit": actual,
            "matches_pin": actual == pin["commit"],
            "tracked_changes": changes.splitlines() if changes else [],
            "submodule_status": submodules.splitlines() if submodules else [],
        }

    uefi = ROOT / "sources" / "Mu-Silicium-marble"
    config_path = uefi / "Resources/Configs/marble.toml"
    config = tomllib.loads(config_path.read_text()) if config_path.is_file() else {}
    board = tomllib.loads((ROOT / "device/board.toml").read_text())
    dxe_path = uefi / "Platforms/Xiaomi/marblePkg/Include/DXE.inc"
    dxe = dxe_path.read_text() if dxe_path.is_file() else ""
    menu_recipe = uefi / "Platforms/Xiaomi/marblePkg/Include/UniXNU.fdf.inc"
    if menu_recipe.is_file():
        dxe += menu_recipe.read_text()
    inputs = [
        "Resources/Configs/marble.toml",
        "Resources/DTBs/marble.dtb",
        "Resources/DTBs/marble.dts",
        "Platforms/Xiaomi/marblePkg/marble.dsc",
        "Platforms/Xiaomi/marblePkg/marble.fdf",
        "Platforms/Xiaomi/marblePkg/Library/MemoryMapLib/MemoryMapLib.c",
    ]
    baseline_path = ROOT / "research/baseline-build.json"
    baseline = json.loads(baseline_path.read_text()) if baseline_path.is_file() else None
    menu_path = ROOT / "research/menu-build.json"
    menu = json.loads(menu_path.read_text()) if menu_path.is_file() else None
    darwin_path = ROOT / "research/darwinboot-build.json"
    darwin = json.loads(darwin_path.read_text()) if darwin_path.is_file() else None
    xnu_path = ROOT / "research/mac-build-20261023/build-report.json"
    xnu = json.loads(xnu_path.read_text()) if xnu_path.is_file() else None
    qemu_path = ROOT / "research/qemu-xnu-20261023/timer-interrupt/result.json"
    qemu = json.loads(qemu_path.read_text()) if qemu_path.is_file() else None
    kernel_hash = digest(ROOT / "out/UNTESTED-marble-early-xnu/marble-early-source-kernel.macho")
    xnu_verified = bool(xnu and xnu.get("kernel_built") and kernel_hash and kernel_hash == xnu.get("kernel_sha256"))
    timer_verified = bool(xnu_verified and qemu and qemu.get("pass") and qemu.get("kernel_sha256") == kernel_hash
                          and qemu.get("globals", {}).get("_armcpu_gic_ready") == 1
                          and qemu.get("globals", {}).get("_armcpu_timer_interrupts", 0) > 0)
    early_path = ROOT / "research/early-boot.json"
    early = json.loads(early_path.read_text()) if early_path.is_file() else None
    early_image_hash = digest(ROOT / "out/UNTESTED-marble-early-boot/marble-real-xnu-early-test.img")
    early_ready = bool(early and early_image_hash and early_image_hash == early["boot"]["image_sha256"]
                       and early_image_hash == early["shim_execution"]["image_sha256"]
                       and early["payload_transport"]["real_fat_to_xnu_timer_interrupt"] == "PASS")
    observation_path = ROOT / "research/hardware-entry-probe-20261023/hardware-observation.json"
    observation = json.loads(observation_path.read_text()) if observation_path.is_file() else None
    probe_path = ROOT / "research/entry-probe-build.json"
    probe = json.loads(probe_path.read_text()) if probe_path.is_file() else None
    probe_image_hash = digest(ROOT / "out/UNTESTED-marble-xnu-entry-probe/marble-xnu-entry-diagnostic.img")
    probe_kernel_hash = digest(ROOT / "out/UNTESTED-marble-xnu-entry-probe/marble-entry-probe-kernel.macho")
    probe_ready = bool(probe and probe_image_hash and probe_kernel_hash
                       and probe_image_hash == probe["boot"]["image_sha256"] == probe["shim_execution"]["image_sha256"]
                       and probe_kernel_hash == probe["boot"]["kernel_sha256"] == probe["qemu_kernel"]["kernel_sha256"]
                       and probe["qemu_kernel"]["pass"] and probe["qemu_marker_pixels"]["pass"]
                       and probe["shim_execution"]["exact_shim_execution"] == "PASS")
    post_path = ROOT / "research/post-mmu-build.json"
    post = json.loads(post_path.read_text()) if post_path.is_file() else None
    post_image_hash = digest(ROOT / "out/UNTESTED-marble-xnu-post-mmu/marble-xnu-post-mmu-reset-test.img")
    post_kernel_hash = digest(ROOT / "out/UNTESTED-marble-xnu-post-mmu/marble-entry-probe-kernel.macho")
    post_ready = bool(post and post_image_hash and post_kernel_hash
                      and post_image_hash == post["boot"]["image_sha256"] == post["shim_execution"]["image_sha256"]
                      and post_kernel_hash == post["boot"]["kernel_sha256"] == post["qemu_post_mmu"]["kernel_sha256"]
                      and post["qemu_post_mmu"]["pass"] and post["shim_execution"]["exact_shim_execution"] == "PASS")
    mmu_observation_path = ROOT / "research/hardware-post-mmu-20261023/hardware-observation.json"
    mmu_observation = json.loads(mmu_observation_path.read_text()) if mmu_observation_path.is_file() else None
    vm_path = ROOT / "research/vm-init-build.json"
    vm = json.loads(vm_path.read_text()) if vm_path.is_file() else None
    vm_hash = digest(ROOT / "out/UNTESTED-marble-xnu-vm-init/marble-xnu-vm-init-test.img")
    vm_kernel_hash = digest(ROOT / "out/UNTESTED-marble-xnu-vm-init/marble-entry-probe-kernel.macho")
    vm_ready = bool(vm and vm_hash and vm_kernel_hash
                    and vm_hash == vm["boot"]["image_sha256"] == vm["shim_execution"]["image_sha256"]
                    and vm_kernel_hash == vm["boot"]["kernel_sha256"] == vm["qemu_vm_init"]["kernel_sha256"]
                    and vm["qemu_vm_init"]["pass"] and vm["qemu_vm_init"]["arm_vm_init_returned"]
                    and vm["shim_execution"]["exact_shim_execution"] == "PASS")
    vm_observation_path = ROOT / "research/hardware-vm-init-20261023/hardware-observation.json"
    vm_observation = json.loads(vm_observation_path.read_text()) if vm_observation_path.is_file() else None
    timer_path = ROOT / "research/timer-build.json"
    timer = json.loads(timer_path.read_text()) if timer_path.is_file() else None
    timer_hash = digest(ROOT / "out/UNTESTED-marble-xnu-timer/marble-xnu-timer-test.img")
    timer_kernel_hash = digest(ROOT / "out/UNTESTED-marble-xnu-timer/marble-entry-probe-kernel.macho")
    timer_ready = bool(timer and timer_hash and timer_kernel_hash
                       and timer_hash == timer["boot"]["image_sha256"] == timer["shim_execution"]["image_sha256"]
                       and timer_kernel_hash == timer["boot"]["kernel_sha256"] == timer["qemu_timer"]["kernel_sha256"]
                       and timer["qemu_timer"]["pass"] and timer["qemu_timer"]["real_timer_interrupt_observed"]
                       and timer["shim_execution"]["exact_shim_execution"] == "PASS")
    timer_observation_path = ROOT / "research/hardware-timer-20261023/hardware-observation.json"
    timer_observation = json.loads(timer_observation_path.read_text()) if timer_observation_path.is_file() else None
    machine_path = ROOT / "research/machine-startup-build.json"
    machine = json.loads(machine_path.read_text()) if machine_path.is_file() else None
    machine_hash = digest(ROOT / "out/UNTESTED-marble-xnu-machine-startup/marble-xnu-machine-startup-test.img")
    machine_kernel_hash = digest(ROOT / "out/UNTESTED-marble-xnu-machine-startup/marble-entry-probe-kernel.macho")
    machine_ready = bool(machine and machine_hash and machine_kernel_hash
                         and machine_hash == machine["boot"]["image_sha256"] == machine["shim_execution"]["image_sha256"]
                         and machine_kernel_hash == machine["boot"]["kernel_sha256"] == machine["qemu_machine_startup"]["kernel_sha256"]
                         and machine["qemu_machine_startup"]["pass"] and machine["qemu_machine_startup"]["machine_conf_returned"]
                         and machine["shim_execution"]["exact_shim_execution"] == "PASS")
    machine_observation_path = ROOT / "research/hardware-machine-startup-20261023/hardware-observation.json"
    machine_observation = json.loads(machine_observation_path.read_text()) if machine_observation_path.is_file() else None
    console_pair_path = ROOT / "research/console-localization-build.json"
    console_pair = json.loads(console_pair_path.read_text()) if console_pair_path.is_file() else None
    console_checkpoints_ready = {}
    if console_pair:
        for name, item in console_pair["checkpoints"].items():
            image_hash = digest(ROOT / ("out/UNTESTED-marble-xnu-" + name) / item["boot"]["image_file"])
            kernel_hash = digest(ROOT / ("out/UNTESTED-marble-xnu-" + name) / "marble-entry-probe-kernel.macho")
            console_checkpoints_ready[name] = bool(image_hash and kernel_hash
                and image_hash == item["boot"]["image_sha256"] == item["shim_execution"]["image_sha256"]
                and kernel_hash == item["boot"]["kernel_sha256"] == item["qemu_checkpoint"]["kernel_sha256"]
                and item["qemu_checkpoint"]["pass"] and item["qemu_checkpoint"]["selected_call_returned"]
                and item["shim_execution"]["exact_shim_execution"] == "PASS")
    serial_observation_path = ROOT / "research/hardware-serial-console-20261023/hardware-observation.json"
    serial_observation = json.loads(serial_observation_path.read_text()) if serial_observation_path.is_file() else None
    console_observation_path = ROOT / "research/hardware-console-init-20261023/hardware-observation.json"
    console_observation = json.loads(console_observation_path.read_text()) if console_observation_path.is_file() else None
    dt_fix_path = ROOT / "research/dt-panic-console-build.json"
    dt_fix = json.loads(dt_fix_path.read_text()) if dt_fix_path.is_file() else None
    dt_fix_hash = digest(ROOT / "out/UNTESTED-marble-xnu-dt-panic-console/marble-xnu-dt-panic-console-test.img")
    dt_fix_kernel_hash = digest(ROOT / "out/UNTESTED-marble-xnu-dt-panic-console/marble-entry-probe-kernel.macho")
    dt_fix_ready = bool(dt_fix and dt_fix_hash and dt_fix_kernel_hash
        and dt_fix_hash == dt_fix["boot"]["image_sha256"] == dt_fix["shim_execution"]["image_sha256"]
        and dt_fix_kernel_hash == dt_fix["boot"]["kernel_sha256"] == dt_fix["qemu_fixed_console_checkpoint"]["kernel_sha256"]
        and dt_fix["compiled_code_audit"]["pass"] and dt_fix["qemu_fixed_source_timer"]["pass"]
        and dt_fix["qemu_fixed_console_checkpoint"]["pass"] and dt_fix["shim_execution"]["exact_shim_execution"] == "PASS")
    fixed_console_path = ROOT / "research/hardware-dt-panic-console-20261023/hardware-observation.json"
    fixed_console = json.loads(fixed_console_path.read_text()) if fixed_console_path.is_file() else None
    fixed_timer_path = ROOT / "research/dt-panic-timer-build.json"
    fixed_timer = json.loads(fixed_timer_path.read_text()) if fixed_timer_path.is_file() else None
    fixed_timer_hash = digest(ROOT / "out/UNTESTED-marble-xnu-dt-panic-timer/marble-xnu-dt-panic-timer-test.img")
    fixed_timer_kernel_hash = digest(ROOT / "out/UNTESTED-marble-xnu-dt-panic-timer/marble-entry-probe-kernel.macho")
    fixed_timer_ready = bool(fixed_timer and fixed_timer_hash and fixed_timer_kernel_hash
        and fixed_timer_hash == fixed_timer["boot"]["image_sha256"] == fixed_timer["shim_execution"]["image_sha256"]
        and fixed_timer_kernel_hash == fixed_timer["boot"]["kernel_sha256"] == fixed_timer["qemu_timer"]["kernel_sha256"]
        and fixed_timer["qemu_timer"]["pass"] and fixed_timer["qemu_timer"]["real_timer_interrupt_observed"]
        and fixed_timer["shim_execution"]["exact_shim_execution"] == "PASS")
    fixed_timer_observation_path = ROOT / "research/hardware-dt-panic-timer-20261023/hardware-observation.json"
    fixed_timer_observation = json.loads(fixed_timer_observation_path.read_text()) if fixed_timer_observation_path.is_file() else None
    post_console_path = ROOT / "research/post-console-localization-build.json"
    post_console = json.loads(post_console_path.read_text()) if post_console_path.is_file() else None
    post_console_ready = {}
    if post_console:
        for name, item in post_console["checkpoints"].items():
            image_hash = digest(ROOT / ("out/UNTESTED-marble-xnu-" + name) / item["boot"]["image_file"])
            kernel_hash = digest(ROOT / ("out/UNTESTED-marble-xnu-" + name) / "marble-entry-probe-kernel.macho")
            post_console_ready[name] = bool(image_hash and kernel_hash
                and image_hash == item["boot"]["image_sha256"] == item["shim_execution"]["image_sha256"]
                and kernel_hash == item["boot"]["kernel_sha256"] == item["qemu_checkpoint"]["kernel_sha256"]
                and item["qemu_checkpoint"]["pass"] and item["qemu_checkpoint"]["selected_call_returned"]
                and item["shim_execution"]["exact_shim_execution"] == "PASS")
    fixed_machine_path = ROOT / "research/hardware-dt-panic-machine-20261023/hardware-observation.json"
    fixed_machine_observation = json.loads(fixed_machine_path.read_text()) if fixed_machine_path.is_file() else None
    idle_path = ROOT / "research/dt-panic-idle-build.json"
    idle = json.loads(idle_path.read_text()) if idle_path.is_file() else None
    idle_ready = bool(idle
        and digest(ROOT / "out/UNTESTED-marble-xnu-dt-panic-idle/marble-xnu-dt-panic-idle-test.img") == idle["boot"]["image_sha256"] == idle["shim_execution"]["image_sha256"]
        and digest(ROOT / "out/UNTESTED-marble-xnu-dt-panic-idle/marble-entry-probe-kernel.macho") == idle["boot"]["kernel_sha256"] == idle["qemu_checkpoint"]["kernel_sha256"]
        and idle["qemu_checkpoint"]["pass"] and idle["shim_execution"]["exact_shim_execution"] == "PASS"
        and all(test["pass"] and test["screen_pixel_check_pass"] and test["screen_visually_reviewed"]
                and test["kernel_sha256"] == idle["boot"]["kernel_sha256"] for test in idle["qemu_panic_tests"].values())
        and len(idle["qemu_panic_tests"]) == 2)
    idle_observation_path = ROOT / "research/hardware-dt-panic-idle-20261023/hardware-observation.json"
    idle_observation = json.loads(idle_observation_path.read_text()) if idle_observation_path.is_file() else None
    cpu_path = ROOT / "research/dt-panic-cpu-build.json"
    cpu = json.loads(cpu_path.read_text()) if cpu_path.is_file() else None
    cpu_ready = bool(cpu
        and digest(ROOT / "out/UNTESTED-marble-xnu-dt-panic-cpu/marble-xnu-dt-panic-cpu-test.img") == cpu["boot"]["image_sha256"] == cpu["shim_execution"]["image_sha256"]
        and digest(ROOT / "out/UNTESTED-marble-xnu-dt-panic-cpu/marble-entry-probe-kernel.macho") == cpu["boot"]["kernel_sha256"] == cpu["qemu_checkpoint"]["kernel_sha256"]
        and cpu["qemu_checkpoint"]["pass"] and cpu["shim_execution"]["exact_shim_execution"] == "PASS"
        and all(test["pass"] and test["screen_pixel_check_pass"] and test["screen_visually_reviewed"]
                and test["kernel_sha256"] == cpu["boot"]["kernel_sha256"] for test in cpu["qemu_panic_tests"].values())
        and len(cpu["qemu_panic_tests"]) == 2)
    cpu_observation_path = ROOT / "research/hardware-dt-panic-cpu-20261023/hardware-observation.json"
    cpu_observation = json.loads(cpu_observation_path.read_text()) if cpu_observation_path.is_file() else None
    opcode_path = ROOT / "research/dt-panic-opcode-build.json"
    opcode = json.loads(opcode_path.read_text()) if opcode_path.is_file() else None
    opcode_ready = bool(opcode
        and digest(ROOT / "out/UNTESTED-marble-xnu-dt-panic-opcode/marble-xnu-dt-panic-opcode-test.img") == opcode["boot"]["image_sha256"] == opcode["shim_execution"]["image_sha256"]
        and digest(ROOT / "out/UNTESTED-marble-xnu-dt-panic-opcode/marble-entry-probe-kernel.macho") == opcode["boot"]["kernel_sha256"] == opcode["qemu_checkpoint"]["kernel_sha256"]
        and opcode["qemu_checkpoint"]["pass"] and opcode["shim_execution"]["exact_shim_execution"] == "PASS"
        and all(test["pass"] and test["screen_pixel_check_pass"] and test["screen_visually_reviewed"]
                and test["kernel_sha256"] == opcode["boot"]["kernel_sha256"] for test in opcode["qemu_panic_tests"].values())
        and len(opcode["qemu_panic_tests"]) == 2)
    opcode_observation_path = ROOT / "research/hardware-dt-panic-opcode-20261023/hardware-observation.json"
    opcode_observation = json.loads(opcode_observation_path.read_text()) if opcode_observation_path.is_file() else None
    vtimer_path = ROOT / "research/vtimer-timer-build.json"
    vtimer = json.loads(vtimer_path.read_text()) if vtimer_path.is_file() else None
    vtimer_ready = bool(vtimer
        and digest(ROOT / "out/UNTESTED-marble-xnu-vtimer-timer/marble-xnu-vtimer-timer-test.img") == vtimer["boot"]["image_sha256"] == vtimer["shim_execution"]["image_sha256"]
        and digest(ROOT / "out/UNTESTED-marble-xnu-vtimer-timer/marble-entry-probe-kernel.macho") == vtimer["boot"]["kernel_sha256"] == vtimer["qemu_checkpoint"]["kernel_sha256"]
        and vtimer["qemu_checkpoint"]["pass"] and vtimer["shim_execution"]["exact_shim_execution"] == "PASS"
        and all(test["pass"] and test["screen_pixel_check_pass"] and test["screen_visually_reviewed"]
                and test["kernel_sha256"] == vtimer["boot"]["kernel_sha256"] for test in vtimer["qemu_panic_tests"].values())
        and len(vtimer["qemu_panic_tests"]) == 2)
    vtimer_ready = bool(vtimer_ready and vtimer["qemu_checkpoint"]["real_timer_interrupt_observed"]
        and vtimer["qemu_checkpoint"]["globals"]["_source_corecrypto14_status"] == 0
        and vtimer["qemu_checkpoint"]["globals"]["_prng_ready"] == 1
        and vtimer["source_build"]["virtual_timer_only_compile_verified"])
    vtimer_observation_path = ROOT / "research/hardware-vtimer-timer-20261023/hardware-observation.json"
    vtimer_observation = json.loads(vtimer_observation_path.read_text()) if vtimer_observation_path.is_file() else None
    wait_path = ROOT / "research/vtimer-wait-build.json"
    wait = json.loads(wait_path.read_text()) if wait_path.is_file() else None
    wait_ready = bool(wait
        and digest(ROOT / "out/UNTESTED-marble-xnu-vtimer-wait/marble-xnu-vtimer-wait-test.img") == wait["boot"]["image_sha256"] == wait["shim_execution"]["image_sha256"]
        and digest(ROOT / "out/UNTESTED-marble-xnu-vtimer-wait/marble-entry-probe-kernel.macho") == wait["boot"]["kernel_sha256"] == wait["qemu_root_wait"]["kernel_sha256"]
        and wait["qemu_root_wait"]["pass"] and wait["qemu_root_wait"]["original_IOLog_return_observed"]
        and wait["qemu_root_wait"]["cyan_band_pixel_check_pass"] and not wait["kernel_probe"]["automatic_reset"]
        and wait["shim_execution"]["exact_shim_execution"] == "PASS"
        and len(wait["qemu_panic_tests"]) == 2
        and all(t["pass"] and t["screen_visually_reviewed"] and t["kernel_sha256"] == wait["boot"]["kernel_sha256"] for t in wait["qemu_panic_tests"].values()))
    wait_observation_path = ROOT / "research/hardware-vtimer-wait-20261023/hardware-observation.json"
    wait_observation = json.loads(wait_observation_path.read_text()) if wait_observation_path.is_file() else None
    report = {
        "stage": "source_xnu_qemu_timer_observed" if timer_verified else ("source_xnu_built" if xnu_verified else ("darwinboot_probe_hardware_observed" if darwin and darwin.get("hardware_boot_tested") else ("darwinboot_probe_built" if darwin and darwin.get("static_validation") == "PASS" else ("unixnu_menu_hardware_observed" if menu and menu.get("hardware_boot_tested") else ("unixnu_menu_built" if menu and menu.get("static_validation") == "PASS" else ("uefi_baseline_built" if baseline and baseline.get("static_validation") == "PASS" else "research_only")))))),
        "baseline": baseline,
        "menu": menu,
        "darwinboot_probe": darwin,
        "source_xnu": {"mac_build": xnu, "local_kernel_hash_verified": xnu_verified,
                       "qemu_timer": qemu, "qemu_timer_verified": timer_verified},
        "temporary_xnu_boot_image_ready": early_ready,
        "temporary_xnu_boot_image": early,
        "hardware_xnu_boot_attempted": bool(observation),
        "hardware_xnu_execution_verified": bool(observation and observation["source_verified_interpretation"]["actual_kernel_entry_demonstrated"]),
        "hardware_xnu_observation": observation,
        "hardware_fixed_timer_observation": fixed_timer_observation,
        "hardware_fixed_machine_observation": fixed_machine_observation,
        "hardware_idle_observation": idle_observation,
        "hardware_cpu_observation": cpu_observation,
        "hardware_opcode_observation": opcode_observation,
        "hardware_virtual_timer_observation": vtimer_observation,
        "hardware_root_wait_observation": wait_observation,
        "live_root_wait_image_ready": wait_ready,
        "live_root_wait_image": wait,
        "virtual_timer_fix_test_image_ready": vtimer_ready,
        "virtual_timer_fix_test_image": vtimer,
        "opcode_diagnostic_image_ready": opcode_ready,
        "opcode_diagnostic": opcode,
        "cpu_panic_diagnostic_image_ready": cpu_ready,
        "cpu_panic_diagnostic": cpu,
        "idle_panic_diagnostic_image_ready": idle_ready,
        "idle_panic_diagnostic": idle,
        "post_console_checkpoints_ready": post_console_ready,
        "fixed_timer_retest_image_ready": fixed_timer_ready,
        "fixed_timer_retest_image": fixed_timer,
        "hardware_fixed_console_observation": fixed_console,
        "hardware_console_init_observation": console_observation,
        "dt_panic_source_fix_console_image_ready": dt_fix_ready,
        "dt_panic_source_fix": dt_fix,
        "legacy_images_have_fixed_pi_panic_address": True,
        "hardware_serial_init_observation": serial_observation,
        "console_checkpoints_ready": console_checkpoints_ready,
        "hardware_machine_startup_observation": machine_observation,
        "machine_startup_reset_image_ready": machine_ready,
        "machine_startup_reset_image": machine,
        "hardware_timer_observation": timer_observation,
        "timer_interrupt_reset_image_ready": timer_ready,
        "timer_interrupt_reset_image": timer,
        "hardware_vm_init_observation": vm_observation,
        "vm_init_reset_image_ready": vm_ready,
        "vm_init_reset_image": vm,
        "hardware_post_mmu_observation": mmu_observation,
        "post_mmu_reset_image_ready": post_ready,
        "post_mmu_reset_image": post,
        "entry_probe_image_ready": probe_ready,
        "entry_probe_image": probe,
        "host": platform.system(),
        "python": platform.python_version(),
        "sources": sources,
        "board_build_guard": board["board"].get("example") is True,
        "uefi_source_values_not_hardware_measurements": {
            "fd_base": config.get("uefi_fd", {}).get("base"),
            "fd_size": config.get("uefi_fd", {}).get("size"),
            "boot_header": config.get("boot_image", {}).get("header_version"),
        },
        "uefi_embeds_unixnu": "UniXNUPkg/" in dxe,
        "uefi_embeds_darwinboot": "DarwinBootPkg/" in dxe,
        "input_sha256": {name: digest(uefi / name) for name in inputs},
        "tools": {name: shutil.which(name) for name in (
            "git", "python3", "make", "clang", "lld-link", "llvm-objcopy",
            "iasl", "nasm", "dtc", "mformat", "qemu-system-aarch64",
            "xcodebuild", "hdiutil", "diskutil",
        )},
        "pending": [
            "Confirm menu Enter/action handling and return to Android on marble",
            "Verify this phone's DTB, memory map, panel and touch variant",
            "Select IPSW identity, component hashes and prelink chain for a later userspace stage",
            "Observe real CPU/GIC/timer interrupt on hardware after the successful arm_vm_init reset witness",
            "Qualify the live-FDT-derived marble ADT, CPU, interrupts, timers and PSCI on hardware",
            "Qualify native UFS, display/input, GPU and power drivers on marble",
            "Measure userdata GPT geometry only if a later storage milestone needs it",
        ],
        "hardware_boot_tested": bool(menu and menu.get("hardware_boot_tested")),
        "hardware_test_scope": darwin.get("hardware_test_scope") if darwin and darwin.get("hardware_boot_tested") else (menu.get("hardware_test_scope") if menu else None),
        "flashable_output": False,
    }
    if early_ready:
        report["stage"] = "marble_early_xnu_test_image_ready"
    if probe_ready:
        report["stage"] = "marble_xnu_entry_probe_ready"
    if report["hardware_xnu_execution_verified"]:
        report["stage"] = "marble_xnu_pre_mmu_hardware_observed"
    if mmu_observation and mmu_observation["source_verified_interpretation"]["post_mmu_reset_witness_matches_expected"]:
        report["stage"] = "marble_xnu_post_mmu_reset_hardware_observed"
    if vm_observation and vm_observation["source_verified_interpretation"]["arm_vm_init_return_reset_witness_matches_expected"]:
        report["stage"] = "marble_arm_vm_init_reset_hardware_observed"
    if timer_observation and not timer_observation["source_verified_interpretation"]["timer_reset_witness_observed"]:
        report["last_positive_hardware_stage"] = report["stage"]
        report["stage"] = "marble_timer_checkpoint_not_observed"
    if machine_observation and not machine_observation["interpretation"]["machine_conf_return_reset_witness_observed"]:
        report["stage"] = "marble_machine_startup_checkpoint_not_observed"
    if serial_observation and serial_observation["source_verified_interpretation"]["serial_init_return_reset_witness_matches_expected"]:
        report["stage"] = "marble_serial_init_reset_hardware_observed"
        report["last_positive_hardware_stage"] = "serial_init_return_reset_witness"
    if console_observation:
        report["stage"] = "marble_console_checkpoint_not_observed_dt_panic_fix_ready" if dt_fix_ready else "marble_console_checkpoint_not_observed"
    if fixed_console and fixed_console["interpretation"]["fixed_console_return_reset_witness_matches_expected"]:
        report["stage"] = "marble_fixed_console_return_reset_hardware_observed"
        report["last_positive_hardware_stage"] = "fixed_console_return_reset_witness"
    if fixed_timer_observation and not fixed_timer_observation["interpretation"]["fixed_timer_reset_witness_observed"]:
        report["stage"] = "marble_fixed_timer_checkpoint_not_observed"
    if fixed_machine_observation and not fixed_machine_observation["interpretation"]["fixed_machine_conf_return_reset_witness_observed"]:
        report["stage"] = "marble_fixed_machine_checkpoint_not_observed_idle_panic_ready" if idle_ready else "marble_fixed_machine_checkpoint_not_observed"
    if idle_observation and idle_observation["interpretation"]["idle_return_reset_witness_matches_expected"]:
        report["stage"] = "marble_idle_return_hardware_observed_cpu_checkpoint_ready" if cpu_ready else "marble_idle_return_hardware_observed"
        report["last_positive_hardware_stage"] = "fixed_cpu_machine_idle_init_return_reset_witness"
    if cpu_observation and cpu_observation["interpretation"]["undefined_kernel_instruction_panic_observed"]:
        report["stage"] = "marble_undefined_instruction_panic_observed_opcode_capture_ready" if opcode_ready else "marble_undefined_instruction_panic_observed"
    if opcode_observation and opcode_observation["source_verified_interpretation"]["faulting_access_identified"]:
        report["stage"] = "marble_CNTP_CTL_EL0_fault_identified_virtual_timer_source_fix_ready" if vtimer_ready else "marble_CNTP_CTL_EL0_fault_identified"
    if vtimer_observation and vtimer_observation["interpretation"]["virtual_timer_interrupt_reset_witness_matches_expected"]:
        report["last_positive_hardware_stage"] = "virtual_timer_interrupt_reset_witness"
        report["stage"] = "marble_virtual_timer_hardware_witness_observed_live_root_wait_ready" if wait_ready else "marble_virtual_timer_hardware_witness_observed"
    if wait_observation and wait_observation["source_verified_interpretation"]["root_device_failure_panic_observed"]:
        report["stage"] = "marble_BSD_root_discovery_reached_no_mountable_root"
        report["last_positive_hardware_stage"] = "BSD_root_discovery_failure_branch_observed"
    # Keep independent VM evidence separate from the phone's hardware milestone.
    vm_root = ROOT / 'research/qemu-ram-root-20261023/vfs-valid/result.json'
    vm_refusal = ROOT / 'research/qemu-ram-root-20261023/vfs-invalid-header/result.json'
    vm_user = ROOT / 'research/qemu-ram-root-20261023/own-process/result.json'
    fixture_hash = digest(ROOT / 'research/mac-ram-root-fixture-20261023/marble-early-source-kernel.macho')
    experiments = {}
    for name, path in [('ram_root', vm_root), ('malformed_root_refusal', vm_refusal), ('own_process', vm_user)]:
        if path.is_file():
            value = json.loads(path.read_text())
            experiments[name] = {'evidence': str(path.relative_to(ROOT)),
                'kernel_hash_matches': bool(fixture_hash and value.get('kernel_sha256') == fixture_hash),
                'pass': value.get('pass'), 'root_mounted': value.get('root_filesystem_mounted', False),
                'failure_stage': value.get('failure_stage'), 'marble_hardware_tested': False}
    report['offline_ram_root_experiments'] = experiments
    report['iphone_inputs'] = {}
    for candidate in ['iphone-ios176-21G80', 'iphone-ios16716-20H392']:
        path = ROOT / 'research' / candidate / 'kernel-qualification.json'
        if path.is_file():
            value = json.loads(path.read_text())
            report['iphone_inputs'][candidate] = {key: value.get(key) for key in
                ['darwin_versions', 'ordinary_arm64_header_accepted', 'exact_source_version_match',
                 'full_component_abi_qualified', 'ios_userspace_boot_demonstrated']}
    print(json.dumps(report, indent=2))
    # 2 means expected not-ready state; source/config health is not boot readiness.
    return 2


if __name__ == "__main__":
    sys.exit(main())

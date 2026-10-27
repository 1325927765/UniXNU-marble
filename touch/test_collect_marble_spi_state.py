import importlib.util
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

SCRIPT = Path(__file__).with_name("collect_marble_spi_state.py")
spec = importlib.util.spec_from_file_location("spi_state", SCRIPT)
spi_state = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = spi_state
spec.loader.exec_module(spi_state)


class MockRunner:
    def __init__(self, state="recovery", props=None, debug_out="/sys/kernel/debug/clk/clk_summary: absent\n",
                 dma_out="[target platform devices: absent]\n"):
        self.state = state
        self.props = props if props is not None else ["marble", "marble", "marble", "POCO F5", "recovery"]
        self.debug_out = debug_out
        self.dma_out = dma_out
        self.calls = []

    def __call__(self, argv, *, timeout, cap):
        self.calls.append((argv, timeout, cap))
        if argv[-1] == "get-state":
            return {"returncode": 0, "stdout": self.state + "\n", "stderr": "", "bytes": len(self.state) + 1}
        script = argv[-1]
        if "getprop" in script:
            output = "\n".join(self.props) + "\n"
            return {"returncode": 0, "stdout": output, "stderr": "", "bytes": len(output)}
        if "/sys/bus/spi/devices/spi0.0" in script:
            output = "spi0.0: absent\n"
        elif "/sys/bus/platform/devices/900000.*" in script:
            output = self.dma_out
        else:
            output = self.debug_out
        return {"returncode": 0, "stdout": output, "stderr": "", "bytes": len(output)}


class CollectorTests(unittest.TestCase):
    def test_wrong_product_stops_before_reads(self):
        with tempfile.TemporaryDirectory() as temp:
            runner = MockRunner(props=["ruby", "ruby", "ruby", "model", "recovery"])
            with self.assertRaises(spi_state.CollectionError):
                spi_state.collect("C:/Android/adb.exe", "serial; touch /tmp/no", Path(temp) / "out.json", runner)
            self.assertEqual(len(runner.calls), 2)
            self.assertTrue(all("/sys/" not in call[0][-1] for call in runner.calls))

    def test_unknown_product_stops_before_reads(self):
        with tempfile.TemporaryDirectory() as temp:
            runner = MockRunner(props=["", "unknown", "", "", "recovery"])
            with self.assertRaises(spi_state.CollectionError):
                spi_state.collect("adb", "s", Path(temp) / "out.json", runner)
            self.assertEqual(len(runner.calls), 2)

    def test_known_marble_reads_allowlist_and_writes_json_once(self):
        with tempfile.TemporaryDirectory() as temp:
            out = Path(temp) / "state.json"
            runner = MockRunner(debug_out="[clk] absent\n[pinmux gpio16]\n",
                                dma_out="iommu_group -> /sys/kernel/iommu_groups/5\n"
                                        "type: DMA\nreserved_regions: none\n")
            report = spi_state.collect("adb-custom", "SERIAL-7", out, runner)
            self.assertTrue(report["product_verified"])
            self.assertEqual(report["adb_state"], "recovery")
            self.assertEqual(json.loads(out.read_text(encoding="utf-8"))["properties"]["ro.product.device"], "marble")
            self.assertIn("gpio16", report["debug_state"]["stdout"])
            self.assertIn("iommu_groups/5", report["dma_bindings"]["stdout"])
            self.assertEqual(len(runner.calls), 5)
            commands = [call[0] for call in runner.calls]
            self.assertTrue(all(cmd[0] == "adb-custom" and cmd[1:3] == ["-s", "SERIAL-7"] for cmd in commands))
            rendered = " ".join(" ".join(cmd) for cmd in commands)
            for forbidden in ("chmod", "mount", "dmesg", "devmem", "reboot", "firmware", "echo >"):
                self.assertNotIn(forbidden, rendered)
            self.assertTrue(all(call[1] == spi_state.TIMEOUT_SECONDS for call in runner.calls))
            self.assertTrue(all(call[2] <= spi_state.PER_COMMAND_CAP for call in runner.calls))
            with self.assertRaises(spi_state.CollectionError):
                spi_state.collect("adb-custom", "SERIAL-7", out, runner)

    def test_command_plan_is_fixed_and_keeps_serial_out_of_shell(self):
        plan = spi_state.command_plan("adb", "odd;serial")
        self.assertEqual(plan[0][-1], "get-state")
        self.assertTrue(all("odd;serial" not in cmd[-1] for cmd in plan[1:]))
        self.assertTrue(all(cmd[-2] == "shell" and len(cmd) == 5 for cmd in plan[1:]))
        self.assertTrue(all(cmd[-1] != "-c" for cmd in plan[1:]))
        shell = " ".join(cmd[-1] for cmd in plan[1:])
        self.assertIn("/sys/kernel/debug/clk/clk_summary", shell)
        self.assertIn("/sys/kernel/debug/regulator/regulator_summary", shell)
        self.assertIn("/sys/kernel/debug/pinctrl/*", shell)
        self.assertIn("spi0.0", shell)
        dma_plan = plan[-1][-1]
        for address in ("900000.*", "9c0000.*", "990000.*"):
            self.assertIn(address, dma_plan)
        for node in ("driver", "of_node", "iommu_group", "coherent_dma_mask",
                     "dma_mask_bits", "runtime_status", "reserved_regions"):
            self.assertIn(node, dma_plan)
        for root in ("/sys/kernel/debug/iommu", "/sys/kernel/debug/arm-smmu",
                     "/sys/kernel/debug/arm_smmu", "/sys/kernel/debug/gpi-dma",
                     "/sys/kernel/debug/qcom_gpi", "/sys/kernel/debug/dmaengine"):
            self.assertIn(root, dma_plan)
        for forbidden in ("chmod", "mount", "dmesg", "devmem", "echo >", ">>"):
            self.assertNotIn(forbidden, dma_plan)

    def test_gpio_filter_matches_only_gpio_16_through_21(self):
        match = re.search(r"grep -E '([^']+)'", spi_state.DEBUGFS_READ)
        self.assertIsNotNone(match)
        grep = shutil.which("grep")
        prefix = []
        if grep:
            prefix = [grep]
        else:
            wsl = shutil.which("wsl")
            if not wsl:
                self.skipTest("neither grep nor WSL is available")
            prefix = [wsl, "grep"]
        fixture = (
            "pin 16 (GPIO_16) muxed\n"
            "gpio16 active\n"
            "pin 21 (GPIO-21) muxed\n"
            "GPIO160 should-not-match\n"
            "GPIO22 should-not-match\n"
        )
        result = subprocess.run(prefix + ["-E", match.group(1)], input=fixture,
                                capture_output=True, text=True, check=True)
        self.assertEqual(result.stdout.splitlines(), [
            "pin 16 (GPIO_16) muxed", "gpio16 active", "pin 21 (GPIO-21) muxed"])

    def test_bounded_runner_rejects_output_overflow(self):
        code = "import sys; sys.stdout.write('x' * 10000)"
        with self.assertRaises(spi_state.CollectionError):
            spi_state.run_bounded([sys.executable, "-c", code], cap=128, timeout=5)

    def test_bounded_runner_times_out(self):
        with self.assertRaises(spi_state.CollectionError):
            spi_state.run_bounded([sys.executable, "-c", "import time; time.sleep(2)"],
                                  cap=128, timeout=0.1)


if __name__ == "__main__":
    unittest.main()

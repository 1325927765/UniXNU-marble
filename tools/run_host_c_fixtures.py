#!/usr/bin/env python3
"""Run synthetic protocol/layout fixtures; no phone, firmware or kernel build."""
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
fixtures = [(name, name + '.c') for name in (
    'goodix9916r_report_decoder', 'goodix9916r_spi_read',
    'marble_gpi_spi_tre', 'marble_smmu_stream')]
fixtures += [('marble_touch_probe_clock', 'MarbleTouchProbeClock.c'),
             ('marble_touch_prereq_layout', None)]
with tempfile.TemporaryDirectory(prefix='marble-host-') as temp:
    for name, source in fixtures:
        output = Path(temp) / name
        command = ['clang', '-Wall', '-Wextra', '-Werror', '-fsanitize=address,undefined',
                   str(ROOT / 'touch' / ('test_' + name + '.c'))]
        if source:
            command.append(str(ROOT / 'touch' / source))
        subprocess.run(command + ['-o', str(output)], check=True)
        subprocess.run([str(output)], check=True)

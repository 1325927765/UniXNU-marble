#!/usr/bin/env python3
"""Collect bounded hardware inputs through ADB. No device writes or reboots."""
import argparse
import datetime
import hashlib
import json
from pathlib import Path
import struct
import subprocess


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--adb', required=True)
    parser.add_argument('--serial', required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    report = {'collected_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
              'scope': 'Read-only Android hardware collection; no reboot, flash or partition access',
              'device_ready': False, 'queries': {}, 'fdt': None}

    def query(name, command, timeout=15):
        try:
            result = subprocess.run([args.adb, '-s', args.serial, *command], capture_output=True, timeout=timeout)
            report['queries'][name] = {'returncode': result.returncode,
                                      'stdout': result.stdout.decode(errors='replace')[:65536],
                                      'stderr': result.stderr.decode(errors='replace')[:4096]}
            return result
        except subprocess.TimeoutExpired:
            report['queries'][name] = {'error': 'ADB request timed out; no retry or device mutation'}
            return None

    def save():
        (args.output / 'hardware.json').write_text(json.dumps(report, indent=2) + '\n')

    result = query('product_device', ['shell', 'getprop', 'ro.product.device'])
    if result is None or result.returncode or result.stdout.strip() != b'marble':
        save()
        raise SystemExit('No responding marble device; see hardware.json')
    report['device_ready'] = True
    for name, command in [
        ('soc', ['shell', 'getprop', 'ro.soc.model']),
        ('kernel', ['shell', 'uname', '-a']),
        ('meminfo', ['shell', 'cat', '/proc/meminfo']),
        ('iomem', ['shell', 'cat', '/proc/iomem']),
        ('dt_paths', ['shell', 'ls', '-ld', '/sys/firmware/fdt', '/sys/firmware/devicetree/base', '/proc/device-tree']),
    ]:
        query(name, command)
    try:
        result = subprocess.run([args.adb, '-s', args.serial, 'exec-out', 'cat', '/sys/firmware/fdt'],
                                capture_output=True, timeout=20)
        data = result.stdout
        if result.returncode or len(data) < 40 or data[:4] != b'\xd0\x0d\xfe\xed':
            report['fdt'] = {'available': False, 'reason': 'Kernel FDT not readable as a binary DTB',
                             'stderr': result.stderr.decode(errors='replace')[:4096]}
        else:
            size = struct.unpack_from('>I', data, 4)[0]
            if not 40 <= size <= len(data) <= 16 * 1024 * 1024:
                raise ValueError('Unexpected FDT size')
            data = data[:size]
            (args.output / 'marble-live.dtb').write_bytes(data)
            report['fdt'] = {'available': True, 'bytes': len(data),
                             'sha256': hashlib.sha256(data).hexdigest(), 'source': '/sys/firmware/fdt'}
    except subprocess.TimeoutExpired:
        report['fdt'] = {'available': False, 'reason': 'Read timed out'}
    save()
    print(json.dumps({'device_ready': report['device_ready'], 'fdt': report['fdt']}, indent=2))


if __name__ == '__main__':
    main()

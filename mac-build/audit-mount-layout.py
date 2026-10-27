#!/usr/bin/env python3
"""Record actual compiler member offsets used by a read-only root observer."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess

p = argparse.ArgumentParser(description=__doc__)
p.add_argument('--object', type=Path, required=True)
p.add_argument('--kernel', type=Path, required=True)
p.add_argument('--output', type=Path, required=True)
a = p.parse_args()
offsets, evidence = {}, {}
for structure, field in [('mount', 'mnt_vfsstat'), ('vfsstatfs', 'f_fstypename')]:
    text = subprocess.check_output(['xcrun', 'dwarfdump', '--name', structure,
                                    '--show-children', str(a.object)], text=True)
    matches = re.findall(r'DW_AT_name\s+\("' + field + r'"\)(?:(?!DW_TAG_member).)*?'
                         r'DW_AT_data_member_location\s+\((0x[0-9a-f]+)\)', text, re.S)
    if len(matches) != 1:
        raise ValueError('Require one actual compiler member offset: ' + field)
    offsets[structure + '.' + field] = int(matches[0], 16)
    evidence[structure] = text
report = {'kernel_sha256': hashlib.sha256(a.kernel.read_bytes()).hexdigest(),
          'object_sha256': hashlib.sha256(a.object.read_bytes()).hexdigest(),
          'offsets': offsets, 'fstypename_offset': sum(offsets.values()),
          'fstypename_bytes': 16, 'compiler_dwarf': evidence}
a.output.write_text(json.dumps(report, indent=2) + '\n')
print(json.dumps({k: v for k, v in report.items() if k != 'compiler_dwarf'}, indent=2))

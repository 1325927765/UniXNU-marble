#!/usr/bin/env python3
"""Refresh only source/object hashes after adding temporary AES stage markers."""
import argparse
import hashlib
import json
from pathlib import Path
import sys

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--tree', type=Path, required=True)
parser.add_argument('--source', type=Path, required=True)
parser.add_argument('--object', type=Path, required=True)
parser.add_argument('--bindings', type=Path, required=True)
args = parser.parse_args()
sys.path.insert(0, str(args.tree / 'kits/NativePrelink'))
import native_prelink as np

data = args.object.read_bytes()
parsed = np.macho(data)
section = next(s for seg in parsed['segments'] for s in seg['sections'] if s['name'] == '__text')
manifest = json.loads(args.bindings.read_text())
manifest['source_cpp_sha256'] = hashlib.sha256(args.source.read_bytes()).hexdigest()
manifest['compiled_text_sha256'] = hashlib.sha256(data[section['fileoff']:section['fileoff'] + section['size']]).hexdigest()
manifest['diagnostic_stage_markers'] = True
args.bindings.write_text(json.dumps(manifest, indent=2) + '\n')
print(json.dumps({key: manifest[key] for key in ('source_cpp_sha256', 'compiled_text_sha256', 'diagnostic_stage_markers')}, indent=2))

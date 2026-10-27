#!/usr/bin/env python3
"""Bind actual iPhone16 AES slots after checking real native-4K class metadata.

The unexercised AES method names retain their source-header annotation scope.
No other firmware's recorded binding addresses are accepted.
"""
import argparse
import hashlib
import json
from pathlib import Path
import struct
import sys

p = argparse.ArgumentParser(description=__doc__)
p.add_argument('--audit', type=Path, required=True)
p.add_argument('--snapshot', type=Path, required=True)
p.add_argument('--layout', type=Path, required=True)
p.add_argument('--candidate', type=Path, required=True)
p.add_argument('--object', type=Path, required=True)
p.add_argument('--aes-source', type=Path, required=True)
p.add_argument('--prelink-directory', type=Path, required=True)
p.add_argument('--output', type=Path, required=True)
a = p.parse_args()
audit, live, layout = [json.loads(x.read_text()) for x in [a.audit, a.snapshot, a.layout]]
data = a.candidate.read_bytes()
if any(x['candidate_sha256'] != hashlib.sha256(data).hexdigest() for x in [audit]) or live['kernel_sha256'] != audit['candidate_sha256']:
    raise ValueError('Candidate/snapshot identity differs')
if live['bounded_timeout_interrupted'] or layout['object_sha256'] != audit['compiled_object_sha256'] or audit['inherited_mismatches']:
    raise ValueError('Need bounded real metadata and the same compiled source interface')
if layout['fields'] != {'superClassLink': 16, 'classSize': 32}:
    raise ValueError('Unexpected compiler metadata layout')
regs = {k: int(v, 16) for k, v in live['system_registers'].items()}
if regs['TCR_EL1'] >> 14 & 3 or regs['TCR_EL1'] >> 30 & 3 != 2 or not regs['SCTLR_EL1'] & 1:
    raise ValueError('Require active native 4K page tables')
meta = bytes.fromhex(live['memory'][audit['read_memory'][0]])
service = bytes.fromhex(live['memory'][audit['read_memory'][1]])
parent = live['indirect_memory'][audit['read_indirect'][0]]
crypto = bytes.fromhex(parent['bytes'])
sizes = [struct.unpack_from('<I', blob, 32)[0] for blob in [meta, crypto, service]]
if sizes != [0x120, 0x88, 0x88] or struct.unpack_from('<Q', crypto, 16)[0] != int(audit['native_ioservice_metaclass'], 16):
    raise ValueError('Actual IOAES/IOCrypto/IOService hierarchy or instance sizes differ')
if struct.unpack_from('<Q', meta, 16)[0] != int(parent['pointer'], 16):
    raise ValueError('Live superclass linkage differs')
sys.path.insert(0, str(a.prelink_directory))
import native_prelink as np
image = np.macho(data)
obj = a.object.read_bytes()
if hashlib.sha256(obj).hexdigest() != audit['compiled_object_sha256']:
    raise ValueError('Actual compiled source object differs')
parsed_object = np.macho(obj)
object_text = next(s for seg in parsed_object['segments'] for s in seg['sections'] if s['name'] == '__text')

def read(va, size):
    o = np.backed_offset(image['segments'], va, size, len(data))
    return data[o:o+size]

def branch(va):
    word, = struct.unpack('<I', read(va, 4))
    if word & 0xfc000000 != 0x14000000:
        raise ValueError('Expected an original destructor tail branch')
    offset = word & 0x3ffffff
    return va + (offset - 0x4000000 if offset & 0x2000000 else offset) * 4

ctors = [int(v, 16) for v in audit['protected_constructor_candidates']]
if len(ctors) != 2:
    raise ValueError('Require both original protected constructor forms')
code = [struct.unpack('<8I', read(v, 32)) for v in ctors]
if any(left != right and index != 2 for index, (left, right) in enumerate(zip(*code))):
    raise ValueError('Original constructor forms differ beyond the parent call')
destinations = []
for va, ins in zip(ctors, code):
    immediate = ins[2] & 0x3ffffff
    destinations.append(va + 8 + (immediate - 0x4000000 if immediate & 0x2000000 else immediate) * 4)
if len(set(destinations)) != 1:
    raise ValueError('Original constructors do not call the same original parent')
destructor = int(audit['methods'][0]['original_target'], 16)
if branch(destructor - 4) != branch(destructor):
    raise ValueError('Original D1/D2 tail semantics differ')
bindings = {name: int(value, 16) for name, value in audit['potential_bindings'].items()}
bindings.update({'__ZN16IOAESAcceleratorC2EPK11OSMetaClass': ctors[0],
                 '__ZN16IOAESAcceleratorD2Ev': destructor - 4,
                 '__ZN16IOAESAccelerator10gMetaClassE': int(audit['actual_metaclass'], 16)})
result = {'original_sha256': audit['original_sha256'], 'candidate_sha256': audit['candidate_sha256'],
          'compiled_subclass_sha256': audit['compiled_object_sha256'], 'source_commit': 'a34964b8c2fec2e83c8e4f68fb7d6fb7e4b2227b',
          'bindings': {n: hex(v) for n, v in bindings.items()}, 'slide': 0x08000000,
          'live_instance_sizes': dict(zip(['IOAESAccelerator', 'IOCryptoAccelerator', 'IOService'], sizes)),
          'compiled_subclass_slots_checked': len(audit['methods']), 'inherited_slot_mismatches': [],
          'protected_constructor_forms': [hex(v) for v in ctors], 'original_parent_constructor': hex(destinations[0]),
          'live_instance_sizes_qualified': True, 'original_code_modified': False,
          'other_device_recorded_bindings_used': False, 'aes_operations_runtime_qualified': False,
          'unexercised_method_names': 'Source ABI header annotations at measured original slots; not independent symbolication',
          'original_hardware_keys_available': False}
result.update(compiled_text_sha256=hashlib.sha256(obj[object_text['fileoff']:object_text['fileoff']+object_text['size']]).hexdigest(),
              source_cpp_sha256=hashlib.sha256(a.aes_source.read_bytes()).hexdigest(),
              source_header_sha256=hashlib.sha256(a.aes_source.with_name('OriginalAESABI.h').read_bytes()).hexdigest())
a.output.write_text(json.dumps(result, indent=2)+'\n')
print(json.dumps(result, indent=2))

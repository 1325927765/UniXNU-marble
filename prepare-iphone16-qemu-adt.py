#!/usr/bin/env python3
"""Describe an unpersonalized, non-Apple-secure-boot QEMU Image4 environment.

These zero status values match the original iPhone DT template. They describe
the custom loader's actual lack of Apple personalization/security state; they
are not an assertion that Apple verified this machine or its boot chain.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import struct

PROPERTIES = ['mix-n-match-prevention-status', 'certificate-security-mode',
    'certificate-production-status', 'effective-security-mode-ap',
    'effective-production-status-ap', 'effective-security-mode-sep',
    'effective-production-status-sep', 'production-cert',
    'amfi-only-platform-code', 'amfi-allows-trust-cache-load']


def read(data, offset=0):
    count, children = struct.unpack_from('<2I', data, offset)
    offset += 8
    props = {}
    for _ in range(count):
        name = data[offset:offset+32].split(b'\0')[0].decode()
        size, = struct.unpack_from('<I', data, offset+32)
        offset += 36
        if size & 0x80000000 or offset+size > len(data):
            raise ValueError('Expected a fully populated bounded QEMU ADT')
        if name in props:
            raise ValueError('Duplicate ADT property')
        props[name] = data[offset:offset+size]
        offset += (size+3) & ~3
    nested = []
    for _ in range(children):
        child, offset = read(data, offset)
        nested.append(child)
    return (props, nested), offset


def encode(node):
    props, children = node
    result = struct.pack('<2I', len(props), len(children))
    for key, value in props.items():
        if len(key.encode()) >= 32:
            raise ValueError('ADT property name too long')
        result += struct.pack('<32sI', key.encode(), len(value))+value+bytes(-len(value) % 4)
    return result+b''.join(encode(child) for child in children)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('adt', type=Path)
    args = parser.parse_args()
    data = args.adt.read_bytes()
    root, end = read(data)
    if end != len(data) or root[0].get('compatible') != b'linux,dummy-virt\0':
        raise ValueError('This fixture is restricted to the explicit QEMU platform')
    chosen = [child for child in root[1] if child[0].get('name') == b'chosen\0']
    if len(chosen) != 1:
        raise ValueError('Expected exactly one chosen node')
    props = chosen[0][0]
    if props.get('crypto-hash-method') != b'sha2-384\0':
        raise ValueError('Require the original iPhone SHA-384 Image4 algorithm')
    for name in PROPERTIES:
        if name in props:
            raise ValueError('Refusing to replace existing security state')
        props[name] = bytes(4)
    # A fresh nonce belongs to this explicit custom-loader boot. The Image4
    # consumer needs its SHA-384 digest even in the declared unpersonalized
    # environment. No Apple signed manifest or authentication is invented.
    nonce = os.urandom(8)
    props['boot-nonce'] = nonce
    manifest = [child for child in chosen[0][1] if child[0].get('name') == b'manifest-properties\0']
    if len(manifest) != 1 or 'BNCH' in manifest[0][0]:
        raise ValueError('Expected an empty owner-controlled nonce digest slot')
    nonce_digest = hashlib.sha384(nonce).digest()
    manifest[0][0]['BNCH'] = nonce_digest
    # Like UniXNU's offline owner-boot-manifest publication, use a separate
    # owner domain for this unsigned boot set. This is not an Apple IM4M or an
    # Apple-personalized identity. Bind the exact files actually handed off.
    domain = b'UniXNU.QEMU.OwnerBootSet.v1\0'
    kernel = args.adt.with_suffix('')
    if not kernel.is_file():
        raise ValueError('Expected the exact adjacent kernel payload')
    # The payload layout is explicit; do not guess which file is the root.
    ramdisk = args.adt.parent / 'ram-root-fixture.img'
    if not ramdisk.is_file():
        raise ValueError('Expected the exact ram-root-fixture.img boot payload')
    owner_set = {'domain': domain[:-1].decode(), 'apple_personalized': False,
                 'kernel_sha384': hashlib.sha384(kernel.read_bytes()).hexdigest(),
                 'initrd_sha384': hashlib.sha384(ramdisk.read_bytes()).hexdigest(),
                 'pre_identity_adt_sha384': hashlib.sha384(encode(root)).hexdigest()}
    owner_bytes = json.dumps(owner_set, sort_keys=True, separators=(',', ':')).encode()
    owner_hash = hashlib.sha384(domain + owner_bytes).digest()
    if 'boot-manifest-hash' in props or 'owner-boot-manifest-domain' in props:
        raise ValueError('Refusing to replace an existing firmware identity')
    props['owner-boot-manifest-domain'] = domain
    props['boot-manifest-hash'] = owner_hash
    output = encode(root)
    args.adt.write_bytes(output)
    args.adt.with_suffix('.image4-context.json').write_text(json.dumps({
        'scope': 'QEMU custom loader, unpersonalized; no Apple secure boot claim',
        'apple_secure_boot_verified': False, 'status_values': {n: 0 for n in PROPERTIES},
        'owner_boot_nonce': nonce.hex(), 'owner_nonce_digest_algorithm': 'sha384',
        'owner_nonce_digest': nonce_digest.hex(),
        'owner_boot_set': owner_set, 'owner_boot_set_sha384': owner_hash.hex(),
        'original_iphone_dt_template': 'research/iphone16-device-tree/device-tree.adt',
        'input_sha256': hashlib.sha256(data).hexdigest(), 'output_sha256': hashlib.sha256(output).hexdigest()
    }, indent=2)+'\n')


if __name__ == '__main__':
    main()

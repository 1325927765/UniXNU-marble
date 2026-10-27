#!/usr/bin/env python3
"""Read an iPhone IPSW manifest/components without downloading its OS volume.

Apple CDN range responses are checked exactly. ZIP64, CRC and extraction limits
are handled before accepting data. This qualifies input identity, not iOS boot.
"""
import argparse
import hashlib
import io
import json
from pathlib import Path
import plistlib
import re
import urllib.parse
import urllib.request
import zipfile


class AppleRanges(io.RawIOBase):
    def __init__(self, url, budget=128 * 1024 * 1024):
        parsed = urllib.parse.urlparse(url)
        if parsed.scheme != 'https' or parsed.hostname != 'updates.cdn-apple.com':
            raise ValueError('Remote input must be an HTTPS Apple firmware CDN URL')
        self.url, self.position, self.total, self.budget = url, 0, 0, budget
        self.size = None
        self.etag = None
        self.requests = []
        self._cache = []
        self._fetch(0, 1)

    def _fetch(self, start, count):
        if count < 0 or self.total + count > self.budget:
            raise ValueError('HTTP extraction budget exceeded')
        end = start + count - 1
        request = urllib.request.Request(self.url, headers={
            'Range': f'bytes={start}-{end}', 'Accept-Encoding': 'identity'})
        with urllib.request.urlopen(request, timeout=60) as response:
            match = re.fullmatch(r'bytes (\d+)-(\d+)/(\d+)', response.headers.get('Content-Range', ''))
            if response.status != 206 or not match or tuple(map(int, match.groups()[:2])) != (start, end):
                raise ValueError('Server did not return the exact requested byte range')
            size = int(match[3])
            etag = response.headers.get('ETag')
            if self.size is not None and (self.size != size or self.etag != etag):
                raise ValueError('Remote archive identity changed during extraction')
            self.size, self.etag = size, etag
            data = response.read(count + 1)
            if len(data) != count:
                raise ValueError('Truncated or oversized HTTP response')
            self.total += count
            self.requests.append({'start': start, 'bytes': count})
            return data

    def seekable(self):
        return True

    def readable(self):
        return True

    def tell(self):
        return self.position

    def seek(self, offset, whence=0):
        position = offset if whence == 0 else self.position + offset if whence == 1 else self.size + offset
        if position < 0 or position > self.size:
            raise ValueError('Seek outside archive')
        self.position = position
        return position

    def read(self, count=-1):
        count = self.size - self.position if count < 0 else min(count, self.size - self.position)
        if not count:
            return b''
        start = self.position
        for base, data in self._cache:
            if base <= start and start + count <= base + len(data):
                self.position += count
                return data[start-base:start-base+count]
        # Small ZIP metadata reads are coalesced, including the ZIP64 trailer.
        fetch_start = max(0, self.size - 131072) if start >= self.size - 131072 else start
        fetch_size = max(count + start - fetch_start, min(65536, self.size - fetch_start))
        data = self._fetch(fetch_start, fetch_size)
        self._cache.append((fetch_start, data))
        if len(self._cache) > 4:
            self._cache.pop(0)
        self.position += count
        return data[start-fetch_start:start-fetch_start+count]


def safe_member(archive, name, limit):
    info = archive.getinfo(name)
    if info.file_size > limit or info.compress_size > limit or info.flag_bits & 1:
        raise ValueError(f'Component exceeds bound or is encrypted: {name}')
    return archive.read(info)  # ZipFile also verifies the member CRC.


def inspect(archive, product, board):
    manifest_bytes = safe_member(archive, 'BuildManifest.plist', 16 * 1024 * 1024)
    manifest = plistlib.loads(manifest_bytes)
    products = manifest['SupportedProductTypes']
    if not products or any(not p.startswith('iPhone') for p in products) or product not in products:
        raise ValueError('Input is not exclusively iPhone firmware for the requested product')
    identities = [i for i in manifest['BuildIdentities'] if i['Info']['DeviceClass'] == board]
    if not identities:
        raise ValueError('Requested iPhone board has no build identity')
    selected = []
    for identity in identities:
        components = {}
        for key, value in identity['Manifest'].items():
            name = value.get('Info', {}).get('Path')
            if not name:
                continue
            info = archive.getinfo(name)
            components[key] = {'path': name, 'bytes': info.file_size,
                               'compressed_bytes': info.compress_size,
                               'manifest_digest': value.get('Digest', b'').hex()}
        selected.append({'device_class': board, 'chip_id': identity['ApChipID'],
                         'board_id': identity['ApBoardID'],
                         'variant': identity['Info'].get('Variant'),
                         'restore_behavior': identity['Info'].get('RestoreBehavior'),
                         'components': components})
    report = {'product_version': manifest['ProductVersion'],
              'product_build': manifest['ProductBuildVersion'], 'supported_products': products,
              'requested_product': product, 'board': board, 'iphone_only': True,
              'build_manifest_sha256': hashlib.sha256(manifest_bytes).hexdigest(),
              'identities': selected, 'kernel_abi_qualified': False,
              'ios_userspace_boot_demonstrated': False}
    return report, manifest_bytes


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('input', help='Local IPSW or HTTPS Apple CDN URL')
    parser.add_argument('--product', required=True)
    parser.add_argument('--board', required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--component', action='append', default=[])
    parser.add_argument('--component-behavior', choices=['Erase', 'Update'], default='Erase')
    parser.add_argument('--max-component-mib', type=int, choices=[96, 128, 256, 512], default=96)
    args = parser.parse_args()
    if not re.fullmatch(r'iPhone\d+,\d+', args.product):
        parser.error('Only an explicit iPhone product is accepted')
    limit = args.max_component_mib * 1024 * 1024
    source = AppleRanges(args.input, budget=max(128 * 1024 * 1024, limit * max(1, len(args.component)) + 4 * 1024 * 1024)) if args.input.startswith('https://') else open(args.input, 'rb')
    args.output.mkdir(parents=True, exist_ok=True)
    with source, zipfile.ZipFile(source) as archive:
        report, manifest = inspect(archive, args.product, args.board)
        (args.output / 'BuildManifest.plist').write_bytes(manifest)
        report['source'] = args.input
        report['extracted_components'] = {}
        report['component_identity_behavior'] = args.component_behavior
        for component in args.component:
            paths = {i['components'][component]['path'] for i in report['identities'] if i['restore_behavior'] == args.component_behavior}
            if len(paths) != 1:
                raise ValueError(f'Restore identities disagree about {component}')
            name = paths.pop()
            data = safe_member(archive, name, limit)
            destination = args.output / Path(name).name
            destination.write_bytes(data)
            report['extracted_components'][component] = {'path': str(destination), 'archive_path': name,
                'sha256': hashlib.sha256(data).hexdigest(), 'bytes': len(data)}
        if isinstance(source, AppleRanges):
            report['http'] = {'archive_bytes': source.size, 'etag': source.etag,
                              'downloaded_bytes': source.total, 'requests': source.requests,
                              'whole_archive_hash_verified': False}
    (args.output / 'qualification.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({k: report[k] for k in ['product_version', 'product_build', 'supported_products',
                                           'board', 'iphone_only', 'extracted_components']}, indent=2))


if __name__ == '__main__':
    main()

#!/usr/bin/env python3
"""Identity/refusal controls for the iPhone-only firmware inspector."""
import importlib.util
import io
import plistlib
from pathlib import Path
import unittest
from unittest.mock import patch
import zipfile

spec = importlib.util.spec_from_file_location('qualify', Path(__file__).with_name('qualify-iphone-ipsw.py'))
qualify = importlib.util.module_from_spec(spec)
spec.loader.exec_module(qualify)


def archive(products):
    stream = io.BytesIO()
    manifest = {'SupportedProductTypes': products, 'ProductVersion': '17.6', 'ProductBuildVersion': '21G80',
        'BuildIdentities': [{'ApChipID': '0x8020', 'ApBoardID': '0x0e',
            'Info': {'DeviceClass': 'd321ap', 'RestoreBehavior': 'Erase'},
            'Manifest': {'KernelCache': {'Info': {'Path': 'kernel'}, 'Digest': b'abc'}}}]}
    with zipfile.ZipFile(stream, 'w') as zipped:
        zipped.writestr('BuildManifest.plist', plistlib.dumps(manifest))
        zipped.writestr('kernel', b'fixture')
    stream.seek(0)
    return zipfile.ZipFile(stream)


class Response(io.BytesIO):
    def __init__(self, status, content_range, etag='stable'):
        super().__init__(b'x')
        self.status = status
        self.headers = {'Content-Range': content_range, 'ETag': etag}


class QualificationTests(unittest.TestCase):
    def test_actual_iphone_identity(self):
        with archive(['iPhone11,2']) as zipped:
            report, _ = qualify.inspect(zipped, 'iPhone11,2', 'd321ap')
        self.assertTrue(report['iphone_only'])
        self.assertFalse(report['kernel_abi_qualified'])

    def test_ipad_and_mixed_inputs_refused(self):
        for products in [['iPad7,1'], ['iPhone11,2', 'iPad7,1']]:
            with archive(products) as zipped, self.assertRaises(ValueError):
                qualify.inspect(zipped, 'iPhone11,2', 'd321ap')

    def test_wrong_product_and_board_refused(self):
        for product, board in [('iPhone10,6', 'd321ap'), ('iPhone11,2', 'j120ap')]:
            with archive(['iPhone11,2']) as zipped, self.assertRaises(ValueError):
                qualify.inspect(zipped, product, board)

    def test_full_response_and_wrong_range_refused(self):
        for status, content_range in [(200, ''), (206, 'bytes 1-1/10')]:
            with patch.object(qualify.urllib.request, 'urlopen', return_value=Response(status, content_range)):
                with self.assertRaises(ValueError):
                    qualify.AppleRanges('https://updates.cdn-apple.com/test.ipsw')

    def test_changed_archive_refused(self):
        with patch.object(qualify.urllib.request, 'urlopen', side_effect=[
            Response(206, 'bytes 0-0/10'), Response(206, 'bytes 1-1/10', 'changed')]):
            source = qualify.AppleRanges('https://updates.cdn-apple.com/test.ipsw')
            with self.assertRaises(ValueError):
                source._fetch(1, 1)

    def test_budget_and_non_apple_source_refused(self):
        with self.assertRaises(ValueError):
            qualify.AppleRanges('https://example.org/test.ipsw')
        with patch.object(qualify.urllib.request, 'urlopen', return_value=Response(206, 'bytes 0-0/10')):
            source = qualify.AppleRanges('https://updates.cdn-apple.com/test.ipsw', budget=1)
            with self.assertRaises(ValueError):
                source._fetch(1, 1)


if __name__ == '__main__':
    unittest.main()

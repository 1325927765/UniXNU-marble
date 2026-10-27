"""Extract generated source, never binaries, from the pinned successful reference CI."""
import hashlib
import json
from pathlib import Path
import tarfile
import zipfile

root = Path(__file__).resolve().parent / 'marble8796-20261024'
archive = root / 'reference-buildtree/buildtree.tgz'
report = dict(repository='dipa-studio/ios-sweet', run_id=39158169212,
              artifact_id=12147962438, commit='fdad0de8dc0e75c5ea84762adc03f7232dc91f19',
              run_url='https://github.com/dipa-studio/ios-sweet/actions/runs/39158169212',
              archive_sha256=hashlib.sha256(archive.read_bytes()).hexdigest(),
              inputs={}, generated={})
prefix = 'build/xnu.obj/DEVELOPMENT_ARM64_SWEET/iokit/DriverKit/'
with tarfile.open(archive) as tar, zipfile.ZipFile(root / 'legacy-iig-sources.zip', 'w', zipfile.ZIP_DEFLATED) as out:
    for member in tar:
        if not member.isfile():
            continue
        name = member.name
        if (name.startswith('xnu/iokit/DriverKit/') and name.endswith(('.iig', '.h'))) or name == 'xnu/iokit/IOKit/IORPC.h':
            payload = tar.extractfile(member).read()
            report['inputs'][name.removeprefix('xnu/')] = hashlib.sha256(payload).hexdigest()
        if name.startswith(prefix) and name.endswith(('.h', '.iig.cpp')):
            basename = name.removeprefix(prefix)
            assert '/' not in basename
            payload = tar.extractfile(member).read()
            assert b'kernelContent' not in payload
            out.writestr('generated/' + basename, payload)
            report['generated'][basename] = hashlib.sha256(payload).hexdigest()
    definitions = [Path(name).stem for name in report['inputs'] if name.endswith('.iig')]
    expected = {name + suffix for name in definitions for suffix in ('.h', '.iig.cpp')}
    assert len(expected) == 34 and set(report['generated']) == expected
    out.writestr('manifest.json', json.dumps(report, indent=2) + '\n')
(root / 'legacy-iig-manifest.json').write_text(json.dumps(report, indent=2) + '\n')
print('Pinned source inputs:', len(report['inputs']), 'Generated source files:', len(report['generated']))

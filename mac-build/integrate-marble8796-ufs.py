"""Connect the local read-only marble driver and explicit HFS diagnostic stops."""
import hashlib
import json
from pathlib import Path
import zipfile

r = Path.home() / 'unixnu-marble8796-build'
source = r / 'xnu'
with zipfile.ZipFile(Path.home() / 'unixnu-marble-kit/ufs-sources.zip') as z:
    manifest = json.loads(z.read('manifest.json'))
    for name, entry in manifest['files'].items():
        payload = z.read(name)
        assert hashlib.sha256(payload).hexdigest() == entry['normalized_sha256']
        path = source / 'iokit/bsddev' / name
        assert not path.exists() or path.read_bytes() == payload
        path.write_bytes(payload)
path = source / 'iokit/bsddev/IOKitBSDInit.cpp'
text = path.read_text()
signature = 'kern_return_t\nIOFindBSDRoot( char * rootName, unsigned int rootNameSize,\n    dev_t * root, u_int32_t * oflags )\n{'
assert text.count(signature) == 1
if '#include "marble_ufs_probe.inc"' not in text:
    text = text.replace(signature, '#include "marble_ufs_probe.inc"\n\n' + signature +
                        '\n    marble_ufs_readonly_probe();\n'
                        '    if (marble_ufs_select_root(rootName, rootNameSize, root, oflags)) return KERN_SUCCESS;')
    path.write_text(text)
path = source / 'bsd/kern/bsd_init.c'
text = path.read_text()
mount_success = '\t\tif (0 == (err = vfs_mountroot())) {\n'
assert text.count(mount_success) == 1
if 'MARBLE HFS ROOT MOUNT OK' not in text:
    text = text.replace(mount_success, mount_success + '''
            unsigned int marble_hfs_stop = 0;
            if (PE_parse_boot_argn("marble_hfs_stop", &marble_hfs_stop,
                sizeof(marble_hfs_stop)) && marble_hfs_stop == 1) {
                struct mount *mp = mountlist.tqh_first;
                if (!mp || strcmp(mp->mnt_vtable->vfc_name, "hfs"))
                    panic("MARBLE HFS ROOT: unexpected mounted filesystem");
                panic("MARBLE HFS ROOT MOUNT OK DEV=%llx FLAGS=%llx",
                    (unsigned long long)(unsigned int)rootdev,
                    (unsigned long long)mp->mnt_flag);
            }
''')
    fail = "\t\trootdevice[0] = '\\0';\n"
    assert text.count(fail) == 1
    text = text.replace(fail, fail + '''
        unsigned int marble_ufs_mode = 0;
        if (PE_parse_boot_argn("marble_ufs_probe", &marble_ufs_mode,
            sizeof(marble_ufs_mode)) && marble_ufs_mode == 9) {
            extern uint64_t marble_ufs_root_read_count(void);
            panic("MARBLE UFS ROOT MOUNT FAIL ERR=%llx READS=%llx",
                (unsigned long long)(unsigned int)err, marble_ufs_root_read_count());
        }
''')
    path.write_text(text)
manifest['integrated_into_8796_source'] = True
manifest['xnu8796_compiled'] = False
(r / 'ufs-integration.json').write_text(json.dumps(manifest, indent=2) + '\n')
print('8796 read-only driver integration prepared; compile and runtime validation pending')

"""Defer the opt-in cache rename until a successful writable HFS mount update."""
import argparse
from datetime import datetime
from pathlib import Path

p = argparse.ArgumentParser(description=__doc__)
p.add_argument('--source-root', type=Path, default=Path.home()/'unixnu-marble8796-build/xnu')
p.add_argument('--apply', action='store_true')
a = p.parse_args()
names = ['bsd/kern/bsd_init.c', 'bsd/vfs/vfs_syscalls.c']
old = {n: (a.source_root/n).read_text() for n in names}
new = dict(old)

def once(s, before, after):
    assert s.count(before) == 1, (before, s.count(before))
    return s.replace(before, after, 1)

new[names[0]] = once(new[names[0]], '#if defined(ARM64_BOARD_CONFIG_MARBLE)\n\tmarble_mg_cache_test();\n#endif\n', '')
new[names[0]] = once(new[names[0]], '#if defined(ARM64_BOARD_CONFIG_MARBLE)\nextern void marble_mg_cache_test(void);\n#endif\n\n', '')
s = new[names[1]]
s = once(s, 'boolean_t root_fs_upgrade_try = FALSE;',
    '#if defined(ARM64_BOARD_CONFIG_MARBLE)\nvoid marble_mg_cache_test(void);\n#endif\n\nboolean_t root_fs_upgrade_try = FALSE;')
anchor = '\treturn error;\n}\n\n/*\n * common mount implementation (final stage of mounting)'
s = once(s, anchor, '''#if defined(ARM64_BOARD_CONFIG_MARBLE)
	/* Run only after mount_common and namei cleanup have completed. */
	if (error == 0 && (flags & MNT_UPDATE) && !(flags & MNT_RDONLY) &&
	    strcmp(fstypename, "hfs") == 0) {
		marble_mg_cache_test();
	}
#endif
''' + anchor)
anchor = '\tif (!vnode_isreg(vp)) {\n\t\tprintf("MARBLE MG CACHE: skipped; source is not a regular file\\n");'
s = once(s, anchor, '''	uint64_t mount_flags = vfs_flags(vnode_mount(vp));
	if (!(mount_flags & MNT_ROOTFS) || (mount_flags & MNT_RDONLY)) {
		printf("MARBLE MG CACHE: skipped; source is not on writable root flags=%llx\\n",
		    (unsigned long long)mount_flags);
		vnode_put(vp);
		return;
	}
''' + anchor)
new[names[1]] = s
print('Validated: no pre-launchd rename; post-success HFS update, actual writable root check')
if a.apply:
    backup = a.source_root/'trace-backups'/datetime.now().strftime('%Y%m%d-mg-cache-timing-%H%M%S')
    for n in names:
        dest = backup/n
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(old[n])
    try:
        for n in names:
            (a.source_root/n).write_text(new[n])
    except Exception:
        for n in names:
            (a.source_root/n).write_text(old[n])
        raise
    print('Applied; backup:', backup)

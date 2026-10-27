"""Stop video-console text after the first GUI swap, preserving panic output.

Uses an atomic flag instead of changing ARM's read-only console selector.
The opt-in marblefb_noconsole=1 flag retains its original default (off).
"""
from pathlib import Path
from datetime import datetime
import argparse

p = argparse.ArgumentParser(description=__doc__)
p.add_argument('--source-root', type=Path, default=Path.home()/'unixnu-marble8796-build/xnu')
p.add_argument('--apply', action='store_true')
a = p.parse_args()
names = ['osfmk/console/serial_console.c', 'iokit/Kernel/arm/MarbleFramebuffer.cpp']
old = {n: (a.source_root/n).read_bytes() for n in names}
new = {}
def once(s, before, after):
    assert s.count(before) == 1, (before, s.count(before))
    return s.replace(before, after, 1)
s = old[names[0]].decode()
s = once(s, 'static inline void\n_cnputs(char *c, int size, bool poll)', '''#if defined(ARM64_BOARD_CONFIG_MARBLE)
static uint32_t marble_video_console_quiet;
void
marble_console_pause_video(void)
{
    os_atomic_store(&marble_video_console_quiet, 1, relaxed);
}
#endif

static inline void
_cnputs(char *c, int size, bool poll)''')
s = once(s, '\textern int disableConsoleOutput;\n\n\tif (disableConsoleOutput) {', '''\textern int disableConsoleOutput;
#if defined(ARM64_BOARD_CONFIG_MARBLE)
    if (os_atomic_load(&marble_video_console_quiet, relaxed) &&
        !console_is_serial() && !panic_active()) {
        return;
    }
#endif

\tif (disableConsoleOutput) {''')
new[names[0]] = s.encode()
s = old[names[1]].decode()
s = once(s, '#include "MarbleSurface.h"', '#include "MarbleSurface.h"\n\nextern "C" void marble_console_pause_video(void);')
s = once(s, '''\t\t\tPE_Video video;
\t\t\tPE_current_console(&video);
\t\t\tPE_initialize_console(&video, kPEDisableScreen);''', '''            /* Keep the late-readonly console selector intact. */
            marble_console_pause_video();''')
new[names[1]] = s.encode()
print('Validated: atomic video-only quiet after GUI swap; panic and serial output retained')
if a.apply:
    backup = a.source_root/'trace-backups'/datetime.now().strftime('%Y%m%d-gui-console-%H%M%S')
    for n in names:
        dest = backup/n
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(old[n])
    try:
        for n in names:
            (a.source_root/n).write_bytes(new[n])
    except Exception:
        for n in names:
            (a.source_root/n).write_bytes(old[n])
        raise
    print('Applied; backup:', backup)

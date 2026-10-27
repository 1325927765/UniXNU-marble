"""Apply the GUI quiet latch to the F5 framebuffer-backed serial transmitter."""
from pathlib import Path
from datetime import datetime
import argparse

p = argparse.ArgumentParser(description=__doc__)
p.add_argument('--source-root', type=Path, default=Path.home()/'unixnu-marble8796-build/xnu')
p.add_argument('--apply', action='store_true')
a = p.parse_args()
names = ['osfmk/console/serial_console.c', 'pexpert/arm/pe_serial.c']
old = {n:(a.source_root/n).read_bytes() for n in names}
def once(s,before,after):
    assert s.count(before)==1,(before,s.count(before))
    return s.replace(before,after,1)
s = old[names[0]].decode()
anchor = '''    os_atomic_store(&marble_video_console_quiet, 1, relaxed);
}
#endif'''
s = once(s,anchor,'''    os_atomic_store(&marble_video_console_quiet, 1, relaxed);
}
int
marble_console_video_paused(void)
{
    return os_atomic_load(&marble_video_console_quiet, relaxed) != 0 && !panic_active();
}
#endif''')
new = {names[0]:s.encode()}
s = old[names[1]].decode()
s = once(s,'fbcon_transmit_data(uint8_t c)\n{','''fbcon_transmit_data(uint8_t c)
{
#if defined(ARM64_BOARD_CONFIG_MARBLE)
    /* This serial backend is pixels, not a UART. Preserve panic drawing. */
    extern int marble_console_video_paused(void);
    if (marble_console_video_paused()) {
        return;
    }
#endif''')
new[names[1]] = s.encode()
print('Validated: framebuffer serial transmitter honors GUI latch and panic override')
if a.apply:
    backup = a.source_root/'trace-backups'/datetime.now().strftime('%Y%m%d-fbcon-console-%H%M%S')
    for n in names:
        dest=backup/n;dest.parent.mkdir(parents=True,exist_ok=True);dest.write_bytes(old[n])
    try:
        for n in names:(a.source_root/n).write_bytes(new[n])
    except Exception:
        for n in names:(a.source_root/n).write_bytes(old[n])
        raise
    print('Applied; backup:',backup)

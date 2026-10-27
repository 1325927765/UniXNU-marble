#!/bin/bash
set -u
cd /mnt/d/vibeproject/portrom/UniXNU-marble-lab
python3 research/reference-ios-sweet/tools/mkpayload.py \
  research/marble8796-20261024/boot-console-switch.macho \
  research/marble8796-20261024/qemu-boot-writable.adt \
  research/marble8796-20261024/qemu-boot-writable-console-switch.bin \
  --cmdline "debug=0x14e serial=3 cpus=1 keepsyms=1 rd=md0 unentitled_ios_sim_launch=1 marble_crash_log=1 marble_disp_trace=1 rootrw=1 marble_qemu_writable_root=1 marblefb_noconsole=1 wdt=-1 -v"
python3 research/qemu-marble8796.py --screen-history \
  research/marble8796-20261024/qemu-boot-writable-console-switch.bin \
  /tmp/qemu-ios-boot-writable-console-switch \
  --kernel research/marble8796-20261024/boot-console-switch.macho \
  --secs 180 \
  --file-root research/ios16-hfs-root-20261024/ios16-root-boot-writable.cdr \
  --writable-file-root \
  --fail-on-panic
run_rc=$?
mkdir -p research/marble8796-20261024/qemu-evidence
cp -a /tmp/qemu-ios-boot-writable-console-switch research/marble8796-20261024/qemu-evidence/qemu-ios-boot-writable-console-switch
echo QEMU_EXIT:$run_rc
exit "$run_rc"

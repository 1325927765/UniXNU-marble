#!/bin/bash
set -u
cd /mnt/d/vibeproject/portrom/UniXNU-marble-lab
python3 research/reference-ios-sweet/tools/mkpayload.py \
  research/marble8796-20261024/boot-swaptrace-v2.macho \
  research/marble8796-20261024/qemu-boot-writable.adt \
  research/marble8796-20261024/qemu-boot-writable-noconsole-v2.bin \
  --cmdline "debug=0x14e serial=3 cpus=1 keepsyms=1 rd=md0 unentitled_ios_sim_launch=1 marble_crash_log=1 marble_disp_trace=1 rootrw=1 marble_qemu_writable_root=1 marblefb_noconsole=1 wdt=-1 -v"
python3 research/qemu-marble8796.py --screen-history \
  research/marble8796-20261024/qemu-boot-writable-noconsole-v2.bin \
  /tmp/qemu-ios-boot-writable-noconsole-v2 \
  --kernel research/marble8796-20261024/boot-swaptrace-v2.macho \
  --secs 240 \
  --file-root research/ios16-hfs-root-20261024/ios16-root-boot-writable-noconsole.cdr \
  --writable-file-root \
  --fail-on-panic
run_rc=$?
mkdir -p research/marble8796-20261024/qemu-evidence
cp -a /tmp/qemu-ios-boot-writable-noconsole-v2 research/marble8796-20261024/qemu-evidence/qemu-ios-boot-writable-noconsole-v2
echo QEMU_EXIT:$run_rc
exit "$run_rc"

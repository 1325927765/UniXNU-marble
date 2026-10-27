#!/bin/bash
set -u
cd /mnt/d/vibeproject/portrom/UniXNU-marble-lab
python3 research/reference-ios-sweet/tools/mkpayload.py \
  research/marble8796-20261024/display-match-persist.macho \
  research/marble8796-20261024/qemu-ios-iomfb-caller-trace.adt \
  research/marble8796-20261024/qemu-ios-display-match-persist.bin \
  --cmdline "debug=0x14e serial=3 cpus=1 keepsyms=1 rd=md0 unentitled_ios_sim_launch=1 marble_crash_log=1 marble_disp_trace=1 -v"
python3 research/qemu-marble8796.py --screen-history \
  research/marble8796-20261024/qemu-ios-display-match-persist.bin \
  /tmp/qemu-ios-display-match-persist \
  --kernel research/marble8796-20261024/display-match-persist.macho \
  --secs 120 \
  --file-root research/ios16-hfs-root-20261024/ios16-root-raw.cdr \
  --fail-on-panic
status=$?
rm -f /tmp/qemu-ios-display-match-persist/mon.sock
mkdir -p research/marble8796-20261024/qemu-evidence
cp -a /tmp/qemu-ios-display-match-persist research/marble8796-20261024/qemu-evidence/qemu-ios-display-match-persist
echo QEMU_EXIT:$status
exit "$status"

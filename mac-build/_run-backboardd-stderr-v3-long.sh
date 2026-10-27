#!/bin/bash
set -u
cd /mnt/d/vibeproject/portrom/UniXNU-marble-lab
python3 research/reference-ios-sweet/tools/mkpayload.py \
  research/marble8796-20261024/display-match-persist-watchdog.macho \
  research/marble8796-20261024/qemu-ios-iomfb-caller-trace.adt \
  research/marble8796-20261024/qemu-ios-backboardd-stderr-v3-long.bin \
  --cmdline "debug=0x14e serial=3 cpus=1 keepsyms=1 rd=md0 unentitled_ios_sim_launch=1 marble_crash_log=1 marble_disp_trace=1 -v"
python3 research/qemu-marble8796.py --screen-history \
  research/marble8796-20261024/qemu-ios-backboardd-stderr-v3-long.bin \
  /tmp/qemu-ios-backboardd-stderr-v3-long \
  --kernel research/marble8796-20261024/display-match-persist-watchdog.macho \
  --secs 130 \
  --file-root research/ios16-hfs-root-20261024/ios16-root-backboardd-stderr-v3.cdr \
  --fail-on-panic
status=$?
rm -f /tmp/qemu-ios-backboardd-stderr-v3-long/mon.sock
mkdir -p research/marble8796-20261024/qemu-evidence
cp -a /tmp/qemu-ios-backboardd-stderr-v3-long research/marble8796-20261024/qemu-evidence/qemu-ios-backboardd-stderr-v3
printf 'QEMU_EXIT:%s\n' "$status"
exit "$status"

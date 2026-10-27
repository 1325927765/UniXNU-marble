# Format 2 migration status (2026-10-27)

Specification/checker revision: UniXNU
0fc0fc1f9ddd0fbd4787738afef38667df5e0a95.
Read the official device-repository, migration, component and porting-record
guides at https://unixnu.com/porting/ before interpreting this status.

## What this revision supplies

- A schema_version=2 board identity for marble / SM7475 / iOS16.7.16-20H392.
- Real public reference Git URLs and 40-hex commits, not REQUIRED sentinels.
- A source-backed, sanitized DTS subset with CPU0, PSCI, GIC, virtual timer,
  and disabled peripheral descriptions. No guessed RAM or framebuffer address.
- An ordered legacy patch input and the published overlay/source inventory.
- The device-package location and explicit startup/ABI integration limits.
- Thirteen substantive porting-record areas with source/evidence references.
- An official Porting record CI check and independent source/host checks.
- Local override and proprietary-input inventories with no private blobs.

## Why a complete format 2 build is still unavailable

At the pinned revision upstream has only the ipados-17.7.11-21H461 OS profile.
Its XNU10063/Darwin23/iPad identity is not this port's XNU8796/Darwin22/iPhone
input. A matching iOS16 profile must be implemented and verified upstream;
a device feed cannot inject an OS profile into the current resolver.

There is no reviewed SM7475 common SoC source with soc.toml in the selected
feeds. Linux/Xiaomi reference code is NOT a substitute for that shared source.
A local SoC override is useful during development but does not make an
unimplemented source or an unpinned configuration ready for publication.

Therefore board.example=true remains a build guard. Components remain
unselected, the defconfig is an explicit migration inventory, and the complete
memory/reservation/ADT and driver startup configuration is not claimed. The
legacy monolithic patch also needs splitting across ARM64/SoC/OS/device layers.
Do not remove the guard merely to silence a resolver/build error.

A Porting record pass validates structured evidence and ownership; it does not
prove profile resolution, a kernel build, working touch or device boot.

## Reproduce the checks

From the pinned main UniXNU checkout, substitute your actual device directory:

    python3 scripts/porting-record.py check --device ../UniXNU-marble
    ./unixnu defconfig marble_defconfig -D ../UniXNU-marble
    ./unixnu status --json -D ../UniXNU-marble
    ./unixnu tree -D ../UniXNU-marble

The record check is expected to pass. Resolver/config/tree currently stop at
the missing reviewed sm7475 SoC source; even a real local SoC override still
needs the missing iOS16 OS profile. These are recorded failures, not waived
checks. See docs/evidence/format2-validation.json for the actual local results.

For the source-only hardware compile:

    dtc -I dts -O dtb -o /tmp/marble-hardware.dtb dts/marble.dts

Its success checks syntax, not full hardware ownership, power, memory or ABI.
Firmware package paths are measured legacy paths. No format 2 firmware build
or transfer to the phone has been performed by this migration.

## Source locks and next implementation work

The reference lock records only independently fetched reference pins. It is
not a resolved full-build lock. The final target lock must include the real
SM7475 common layer and selected ABI-compatible components after upstream
profile integration, followed by actual defconfig/fetch/status/tree, build,
payload, firmware, boot-image and device verification.

Keep historical legacy Hello evidence separate. The exact tested latest Mac
kernel tree has not been exported as a new snapshot while the Mac is offline.
No firmware, IPSW, root image, raw phone capture or tester archive belongs here.

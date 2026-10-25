# Device status

Last updated: 2026-10-25.

These are maintainer observations from the existing experimental port. No reproducible public source build or independent verification is claimed by this documentation-only repository.

| Area | Observed result | Remaining work |
| --- | --- | --- |
| Target | POCO F5, marble, SM7475-AB; iPhone iOS 16.7.16 / 20H392 | Publish reviewed, pinned device and OS inputs |
| Kernel and boot | Experimental XNU 8796 temporary boots reached iPhone userspace | Reproduce from publishable source and document the boot chain |
| Storage | Experimental UFS/root access supported progression to Hello | Publish reviewed implementation and define supported filesystem behavior |
| Display | iPhone Hello interface visible on the physical display | Confirm console handoff behavior, rendering stability and supported display path |
| Input | Goodix touch works in Android recovery | Implement and verify XNU controller integration, touch reports and IOHID events |
| Setup | Hello interface observed | Verify physical interaction, setup completion and activation behavior |
| Current UniXNU format | Migration being prepared locally | Resolve matching SM7475 and iOS 16 profiles, source pins, configuration, build and porting-record checks |
| Other hardware | No support claim | GPU acceleration, networking, audio, modem, cameras, sensors and power management need separate implementation/verification |

## Publication milestones

1. Establish this community repository with accurate scope and contribution guidance.
2. Publish reviewed source dependencies, licenses and reproducible device configuration.
3. Verify physical touchscreen input and a stable graphical session on the F5.
4. Publish supported build/test instructions and structured porting records.
5. Request upstream device-catalog registration when its requirements are met.

There is no release schedule yet. A visible Hello screen is a bring-up milestone, not evidence of a usable phone.

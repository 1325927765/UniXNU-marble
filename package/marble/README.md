# Marble board package integration

The device package is mounted at kits/marble by the format 2 resolver.
Current legacy board source is in legacy-xnu/overlay/, device/early/ and touch/.
It is not copied into a fake modern Kit.toml with nonexistent binaries.

Pending: a reviewed SM7475 shared SoC source, an upstream iOS 16.7.16 profile,
ABI-compatible component recipes, and DSC/FDF startup integration. Until these
exist, this directory declares no driver/kext binaries and board.example stays
true. The legacy monolithic patch must be split into its proper ownership
layers; publishing its path is not proof it applies to a modern build stack.

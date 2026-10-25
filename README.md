# UniXNU-marble

**A community device bring-up project for POCO F5 / Redmi Note 12 Turbo (`marble`, Qualcomm SM7475-AB).** The target is **iPhone iOS 16.7.16, build 20H392**.

This repository documents an experimental port and coordinates community work. It is not an official UniXNU-supported device, a complete device tree, or an installable release. The public repository currently contains project documentation only; no reproducible source build is published yet.

> **Current result:** an experimental XNU 8796 image has reached the iOS Hello setup interface on a POCO F5. The display is now reported clean, without the earlier scrolling console text. **The touchscreen does not work in iOS**, so setup cannot currently be completed on the phone.

## Project at a glance

| Item | Current target / result |
| --- | --- |
| Android device | POCO F5 / Redmi Note 12 Turbo |
| Device codename | `marble` |
| SoC | Qualcomm SM7475-AB (Snapdragon 7+ Gen 2 family) |
| iOS target | iPhone iOS 16.7.16 / build 20H392 |
| Kernel family used in the experimental bring-up | XNU 8796 |
| Latest visible milestone | iOS Hello setup screen; clean background reported |
| Physical touch in iOS | **Not working** |
| Public reproducible build / flash instructions | **Not available** |

## Bring-up status

The observations below describe the maintainer's experimental legacy boot path. They are not results from a completed build using the current UniXNU device-repository format.

| Area | Observed | Still needed |
| --- | --- | --- |
| Boot and kernel | Experimental XNU 8796 boots into iOS userspace | Publish pinned inputs and reproducible build steps |
| Display | Hello setup screen appeared; the latest reported screen has no scrolling console text | Repeatable cold-boot test and stable display/session verification |
| Storage | Experimental UFS/root work progressed far enough to reach Hello | Review and publish the implementation; test persistence and filesystem behavior |
| Touch controller | Goodix touch works in Android recovery | XNU-side SPI/controller integration, interrupt handling, coordinate reports and IOHID delivery |
| Setup | Hello screen observed | Working touch, setup completion and activation behavior |
| Other hardware | No support claimed | Wi-Fi, cellular, audio, cameras, sensors, GPU acceleration and power management each need separate work |
| Official UniXNU format | Migration draft exists locally; this public repo does not contain it | Match the iOS profile and SM7475 support, finish configuration, build, and porting records |

**A Hello screen is a bring-up milestone, not a usable-phone claim.** Recovery touch is evidence that the Android recovery environment can read the controller; it does not mean iOS has a working touch driver.

## Source references

These are the upstream projects and public references informing the work. They are references, not a claim that every source has been integrated or validated on the F5.

| Source | How it is used / limitation |
| --- | --- |
| [UniXNU](https://github.com/UniXNU/UniXNU) | Porting framework and device-repository conventions. The current official tree does not yet provide a verified matching iPhone iOS 16.7.16 + SM7475 configuration for this device. |
| [UniXNU device-repository guide](https://unixnu.com/porting/device-repository), [migration guide](https://unixnu.com/porting/migration), and [porting records](https://unixnu.com/porting/records) | Publication and migration requirements. This project has not completed the official checklist or been registered in the upstream device catalog. |
| [Apple XNU source](https://github.com/apple-oss-distributions/xnu), XNU 8796 line | Kernel-family reference for the experimental bring-up. A matching, pinned and reproducible public build recipe is not included here yet. |
| [MiCode Xiaomi kernel sources](https://github.com/MiCode/Xiaomi_Kernel_OpenSource/tree/marble-s-oss) | Android-side `marble` hardware and device-tree reference. Android kernel code is not an iOS driver and must not be treated as proof of XNU support. |
| [UniXNU QcomGeniSpi](https://github.com/UniXNU/QcomGeniSpi) | Candidate Qualcomm GENI SPI reference for investigating Goodix transport. It is not integrated or verified as a complete F5 touch solution. |
| [qine233/UniXNU-clover](https://github.com/qine233/UniXNU-clover) | Community device repository used as an example of how a device port can organize configurations, drivers, notes, patches and packaging. Its clover-specific code is not a source for marble hardware support. |

Apple system images, proprietary firmware and device-specific blobs are not included. Each future source addition must identify its exact revision, origin, applicable license and the device test that supports any claim made about it.

## Repository contents

This is a documentation-first community repository. It does not yet mirror the complete directory layout of more mature ports such as `UniXNU-clover`.

- [STATUS.md](STATUS.md) — evidence boundaries, current status and publication milestones.
- [CONTRIBUTING.md](CONTRIBUTING.md) — how to report results and propose work safely.
- [LICENSE](LICENSE) — license for original documentation in this repository only.

The goal is to publish a reviewable device repository, including a source-backed **device tree** and board configuration, driver code, patches, build/package scripts and per-subsystem test records. Device-tree entries will be tied to identifiable hardware sources and checked on the F5; Android device-tree data will be treated as a reference, not copied as if it were already a working iOS configuration. Components will be added when their provenance, license and reproduction steps are clear. Empty or guessed values will not be presented as working support.

## Roadmap

1. Finish investigating the Goodix touch path from the controller through Qualcomm GENI SPI and XNU's input stack.
2. Validate touch reports and interaction with the Hello interface on the physical F5.
3. Publish a reviewed device tree, board configuration, drivers and patches with pinned revisions, provenance and licenses.
4. Complete the current UniXNU device format, reproducible build/package instructions and porting records against matching OS and SoC support.
5. Expand hardware support and publish results by subsystem, based on repeatable device tests.

There is no release date. The immediate technical blocker is iOS-side physical touch input.

## Community

Use [GitHub Issues](https://github.com/sing0626/UniXNU-marble/issues) for focused questions, hardware findings and implementation proposals. Include the device variant, source revision, exact test performed, expected result and observed result. Mark untested findings as untested.

Please do not post personal identifiers, credentials, private device captures, IPSWs, Apple system images or proprietary firmware. Read [CONTRIBUTING.md](CONTRIBUTING.md) before submitting code or logs.

## License

The [MIT License](LICENSE) applies only to original documentation in this repository. It does not license unpublished port code, Apple-derived material, firmware, or third-party software. Future contributions must retain their applicable licenses.

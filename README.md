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

When implementation is ready for review, the repository can grow to include source-backed board configuration, driver code, patches, build/package scripts and test records, with third-party licenses preserved. Empty or guessed configuration values will not be presented as working support.

## Roadmap

1. Finish investigating the Goodix touch path from the controller through Qualcomm GENI SPI and XNU's input stack.
2. Validate touch reports and interaction with the Hello interface on the physical F5.
3. Publish reviewed source with pinned revisions, provenance, licenses and reproducible build instructions.
4. Complete the current UniXNU device format and its porting records against matching OS and SoC support.
5. Expand hardware support and publish results by subsystem, based on repeatable device tests.

There is no release date. The immediate technical blocker is iOS-side physical touch input.

## Community

Use [GitHub Issues](https://github.com/sing0626/UniXNU-marble/issues) for focused questions, hardware findings and implementation proposals. Include the device variant, source revision, exact test performed, expected result and observed result. Mark untested findings as untested.

Please do not post personal identifiers, credentials, private device captures, IPSWs, Apple system images or proprietary firmware. Read [CONTRIBUTING.md](CONTRIBUTING.md) before submitting code or logs.

## 中文（香港）

呢個係 **POCO F5／Redmi Note 12 Turbo（`marble`，Qualcomm SM7475-AB）移植 iOS 嘅社群研究項目**，目標係 **iPhone iOS 16.7.16（20H392）**。

### 目前做到邊度

- 實驗版 XNU 8796 曾經喺 POCO F5 開到 iOS Hello 設定畫面。
- 最新一次回報嘅 Hello 背景已經乾淨，冇再見到之前嘅滾動 console 文字。
- **iOS 入面嘅實體觸控仍然未能操作。** Android Recovery 入面 Goodix 觸控正常，唔代表 iOS 已有相應驅動。
- 因為觸控未通，未能喺手機上完成設定；亦未驗證啟用、長時間穩定性或日常使用。
- 公開 repo 暫時係文件為主，未有可重現嘅完整 source build、刷機步驟或可下載映像。
- Hello 畫面係 bring-up 里程碑，唔代表已經有可日用嘅 iPhone。

### 參考來源

- [UniXNU 主 repo](https://github.com/UniXNU/UniXNU) 同 [裝置 repo 指引](https://unixnu.com/porting/device-repository)：參考建置框架同官方裝置 repo 格式；`marble` 仲未完成官方格式移植及登記。
- [Apple XNU source](https://github.com/apple-oss-distributions/xnu)：XNU 8796 核心系列嘅公開參考；本 repo 暫時未提供可重現嘅固定版本建置流程。
- [MiCode marble Android kernel source](https://github.com/MiCode/Xiaomi_Kernel_OpenSource/tree/marble-s-oss)：只用作了解 `marble` Android 側硬件／裝置樹資料，唔係 iOS 驅動。
- [UniXNU QcomGeniSpi](https://github.com/UniXNU/QcomGeniSpi)：研究 Qualcomm GENI SPI／Goodix 傳輸嘅候選參考，未整合成可用觸控方案。
- [UniXNU-clover 社群裝置 repo](https://github.com/qine233/UniXNU-clover)：參考成熟裝置 repo 點樣整理設定、驅動、筆記、patch 同 package；clover 專用程式碼唔代表支援 marble。

Apple 系統映像、IPSW、專有韌體同裝置私隱資料唔會放入 repo。之後每份程式碼都要交代來源、版本、授權同實機驗證範圍。

### 下一步

目前首要工作係打通 Goodix 控制器、Qualcomm GENI SPI、XNU input stack 到 IOHID 嘅實體觸控路徑，並喺 F5 上驗證 Hello 畫面可以操作。之後先逐步公開有來源、有授權、可重現嘅設定同建置流程。

歡迎用 [GitHub Issues](https://github.com/sing0626/UniXNU-marble/issues) 提交硬件資料、問題或實作建議。請標明測試過程同結果，未實測嘅內容要清楚註明。

## License

The [MIT License](LICENSE) applies only to original documentation in this repository. It does not license unpublished port code, Apple-derived material, firmware, or third-party software. Future contributions must retain their applicable licenses.

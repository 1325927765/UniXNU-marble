# UniXNU-marble

Experimental community source port for **POCO F5 / Redmi Note 12 Turbo (`marble`, SM7475-AB)**, targeting **iPhone iOS 16.7.16 / 20H392**, using XNU 8796.

**Source is now published. This is a development source collection, not a supported ROM or a verified one-command build.** It is separate from the current official UniXNU format-2 migration and is not an official supported-device registration.

The maintainer's F5 has reached the real iOS Hello interface with a clean display. **Physical touch does not work; setup has not been completed.** The newer prerequisite-probe kernel regressed to a persistent Apple Logo in two runs; the older clock-probe kernel reached Hello again. Neither a Logo nor Hello establishes a usable phone.

## Format 2 record

The root now includes `board.toml`, `feeds.toml`, a reference-only `unixnu.lock`, `configs/`, `dts/`, `patches/xnu/series`, `package/`, input inventories and [porting.toml](porting.toml). [Migration status](docs/FORMAT2-MIGRATION.md) lists what is checked and what is missing. The official checker covers 13 areas; it does not prove the target builds. `board.example=true` remains until a matching iOS16 OS profile and reviewed SM7475 shared source exist. [Hardware inventory](docs/HARDWARE.md) deliberately omits unverified RAM/reservation values.

## What is here

| Path | Contents |
| --- | --- |
| [legacy-xnu/](legacy-xnu/) | 68-path XNU patch, 202 overlay files, notices, exact snapshot hashes, and 34 pinned generated IIG source files |
| [touch/](touch/) | Goodix protocol decoders, SPI framing, clock probe, GPI TRE builder, SMMU decoder, read-only prerequisite snapshot and host fixtures |
| [mac-build/](mac-build/) | Kernel integration/update/diagnostic tools and historical build runners |
| Root Python scripts | ADT, payload, boot-image packaging and lab verification tools |
| [device/early/](device/early/) | Temporary boot shim and read-only in-memory payload transport source |
| [device/classmates/](device/classmates/) | Windows installer source and fake-fastboot tests; no payload or real-device operation in CI |
| [tools/](tools/) | Source integrity checks and metadata/source exporters |
| [BUILDING.md](BUILDING.md) | Public inputs, snapshot reconstruction, build limitations and offline checks |
| [LICENSING.md](LICENSING.md) | Original-code licensing and upstream notices/provenance boundaries |
| [SOURCE-INDEX.json](SOURCE-INDEX.json) | SHA-256 inventory of this publication |

The v4 XNU snapshot is **older than the later touch-probe kernels**. Current touch modules and update scripts are included separately; this source collection has not been rebuilt from a fresh public checkout to reproduce the physical Hello result. Do not apply all historical patch scripts in filename order.

## Current evidence

| Area | Observed | Missing / limitation |
| --- | --- | --- |
| Kernel / userspace | Original experimental kernel reached Hello again in the 2026-10-26 rollback recording | Exact clean source-to-device reproduction |
| Display | Apple Logo and multilingual Hello; clean background after GUI takeover | Broader stability and rendering validation |
| Storage | Native UFS path and HFS root progressed through launchd to Hello | Broader device/SKU/persistence testing |
| Goodix | Recovery input; temporary S4 enable, SE register reads and restoration; read-only prerequisites returned | GPI provider, verified DMA mappings, actual Goodix transaction and HID events |
| Touch | No working iOS input | Setup interaction |
| New probe kernel | Mode 3 and mode 0 both stayed at Logo for 6 and 5 minutes | Diagnose UI services after the console-quiet transition; distinguish runtime timing from link-layout changes |
| Other hardware | No working support claimed | Wi-Fi, cellular, audio, camera, sensors, GPU acceleration and power management |

## No system images in this repository

There is **no IPSW, iOS root filesystem, boot image, proprietary firmware, device dump, private capture, credential or private key** here. The private classmates ZIP is not a public source release and is not uploaded to GitHub. Each tester supplies their own system/firmware inputs. Generated trust-cache tables are regenerated from the tester's inputs, not bundled.

The installer defaults to checks only. A real installation overwrites **userdata**, requires an explicit serial and typed wipe confirmation, and temporarily starts `boot.img`; it does not flash the boot partition. The clean restore-derived root plus the selected kernel has **not** been validated together on hardware. See [device/classmates/README.md](device/classmates/README.md).

## Checks and contributions

See [BUILDING.md](BUILDING.md) for the offline checks. CI checks source hashes/Python syntax, host C fixtures and a Windows installer against a fake fastboot executable. CI does not download Apple images, build the whole kernel, flash phones or certify hardware support.

Use [Issues](https://github.com/sing0626/UniXNU-marble/issues) for subsystem work and [pull requests](https://github.com/sing0626/UniXNU-marble/pulls) for changes. Please keep provenance, notices and tested/unverified claims explicit. Reports should identify the source revision, device SKU and observed behavior without personal identifiers.

## 中文簡介

已公開現有可匯出的移植原始碼、核心快照、觸控原型、建置／封包工具同安裝腳本。
F5 曾入到真正 iOS Hello，但觸控仍未完成；新診斷核心亦有停 Logo 的回歸。
舊核心快照唔等於最新測試核心，完整乾淨重建尚未驗證。iOS 系統檔、私人備份同 7 GB 私人測試包唔會放入公開 repo。

Original Marble-authored code/documentation is offered under [MIT](LICENSE), except where a file specifies another license. Existing SPDX identifiers, XNU/APSL and third-party notices continue to apply; see [LICENSING.md](LICENSING.md).

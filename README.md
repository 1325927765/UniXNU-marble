# UniXNU-marble

Community device project for **POCO F5 / Redmi Note 12 Turbo (`marble`, Qualcomm SM7475-AB)**, targeting **iPhone iOS 16.7.16 (20H392)**.

This repository is the public coordination home for the Marble port. It currently contains documentation only. Reviewed, reproducible device sources will be added as they are ready. This is a community project; it is not an official UniXNU-supported device or an installable release.

## Current status

In the maintainer's existing experimental XNU 8796 setup, the POCO F5 has reached the iPhone Hello setup interface. Display output and storage access sufficient to reach that interface have been observed.

- Physical touchscreen input in iOS is **not working yet**. Working Goodix touch in Android recovery does not establish iOS input support.
- Setup completion, activation, long-term stability and daily use have not been validated.
- There is no supported installation procedure or downloadable boot image here.
- Migration to UniXNU's current device-repository format is unfinished. The existing Hello result does not validate a build with that format.

See [STATUS.md](STATUS.md) for the evidence boundaries and [CONTRIBUTING.md](CONTRIBUTING.md) to help.

## Source publication

The initial publication intentionally contains no unfinished board template, placeholder source pins, kernel patch dump, proprietary firmware, IPSW, root filesystem, or device capture. Device configuration and code will be published after their dependencies, provenance, licensing and reproduction steps are checked.

The intended layout follows the official [device repository guide](https://unixnu.com/porting/device-repository) and [porting records](https://unixnu.com/porting/records). This repository has not yet completed that checklist or been registered in the upstream device catalog.

## 中文（香港）

呢度係 POCO F5／Redmi Note 12 Turbo（marble）嘅 UniXNU 社群移植倉庫，目標係 **iPhone iOS 16.7.16**。

現有實驗版本曾經到達 Hello 設定畫面，但 **iOS 實體觸控未完成**，亦未驗證完成設定、啟用或日常使用。現階段先公開進度同協作文件；未完成嘅設定、驅動及未核對授權嘅來源暫時唔會上傳，亦未提供刷機包。

歡迎透過 Issues 討論實體觸控、顯示同可重現建置；貢獻前請閱讀 [CONTRIBUTING.md](CONTRIBUTING.md)。

## License

The original documentation in this repository is provided under the [MIT License](LICENSE). This does not license any unpublished port code or third-party software. Future source additions must retain their applicable licenses.

# Private tester installer source

This directory publishes the Windows installer and its fake-fastboot tests, not a ROM download. Users supply a separately prepared `manifest.json`, `rootfs.simg`, `boot.img` and Windows platform-tools. No system image or precompiled boot payload is committed.

The installer defaults to hash/device checks. `-Install -Serial <serial>` requires the typed phrase `ERASE USERDATA <serial>` and flashes only `userdata` before issuing a temporary `fastboot boot`. `-BootOnly` starts the selected boot payload against an already installed root and does not require the root image file. Device preflight checks exact product `marble`, unlocked bootloader, bootloader fastboot mode, partition capacity and download limit. Never use this for F5 Pro or another product.

Manifest structure:

```json
{
  "supportedProduct": "marble",
  "expandedRootBytes": 17179869184,
  "payloads": {
    "rootfs": {"file": "rootfs.simg", "bytes": 0, "sha256": "REPLACE_WITH_ACTUAL_SHA256"},
    "boot": {"file": "boot.img", "bytes": 0, "sha256": "REPLACE_WITH_ACTUAL_SHA256"}
  }
}
```

The placeholders are intentionally invalid. Derive lengths/hashes from the caller's own qualified inputs. Never make a manifest by copying another device's private backup. Keep a device-appropriate Android recovery method ready: replacing userdata is destructive, and temporary boot does not restore its Android filesystem.

The maintainer's old kernel reached Hello, but the clean restore-derived root plus that kernel has not been validated together. Apple Logo is not a success certificate, touch is not working, and a fastboot OKAY only means a command was accepted. The installer log uses command-accepted statuses accordingly.

Run `Test-Install-MarbleTest.ps1` for isolated Windows mock tests. It does not use real phones or system images.

# Source reconstruction and offline checks

## Publication boundaries

This is a source publication, not a claim of a reproducible full build. The legacy v4 snapshot predates the current touch probes. Missing exact HFS/BearSSL pins and the absence of a clean end-to-end rebuild are recorded in [legacy-xnu/SOURCE-REVIEW.md](legacy-xnu/SOURCE-REVIEW.md). Mac-side changes after that snapshot are represented by local integration tools and current touch modules, not a newly exported exact Git tree.

`mac-build/` contains historical, anchor/hash-guarded updates for particular intermediate trees. They are not a linear migration sequence. Several lab tools refer to unshipped `research/`, `sources/` or `out/` inputs. Those inputs must be supplied or regenerated; changing a path does not validate a different firmware or device.

## Reconstruct the v4 source baseline

1. Clone `https://github.com/apple-oss-distributions/xnu.git` into a separate checkout.
2. Check out base `1b191cb58250d0705d8a51287127505aa4bc0789`. Begin with a clean tree.
3. Run `git apply --check` with `legacy-xnu/patches/xnu-changes.review.patch`, then apply that patch.
4. Copy the contents of `legacy-xnu/overlay/` into the XNU checkout, preserving paths and source bytes. Fourteen imported files are not UTF-8; do not re-encode them.
5. Inspect the current `touch/` modules and the relevant guarded scripts under `mac-build/` before integrating a later probe. The v4 snapshot does not automatically include those probes.

The source manifest records the patch and overlay hashes. `sources.lock.json` retains historical upstream pins; its old experiment status is not the current hardware status.

## External inputs and toolchain

- macOS, Xcode/SDK and the XNU build support expected by the legacy port; the exact supported toolchain matrix has not been locked for this source publication.
- Public UniXNU / DarwinBoot and marble Mu-Silicium sources at the recorded pins. Local DarwinBoot/UEFI changes live in `device/early/` and lab tooling; a public fresh firmware build has not been qualified.
- The legacy IIG compatibility shim is `mac-build/legacy-iig8796.py`. It can use `MARBLE_BUILD_ROOT` and `MARBLE_IIG_CACHE`; the latter defaults to the included `legacy-xnu/iig/`. Its 34 generated source files are pinned to the exact upstream input hashes in `legacy-xnu/iig/manifest.json`. It refuses mismatched inputs. These are generated C++/header source, not compiled binaries.
- Packaging helpers from `https://github.com/dipa-studio/ios-sweet` (local reference checkout used revision `45263bee51df4a0f55cdf9c649af886399488ddb`). Read that project's own notices and instructions.
- A tester-provided matching iPhone iOS 16.7.16 / 20H392 restore input. The trust-cache exporter in `tools/export-marble8796-cryptex-amfi.py` verifies the expected manifest/component hashes and emits the missing generated CDHash include. Its input/output layout is described by the source; it does not fetch a system image.
- Device-qualified FDT and firmware/run inputs. `pack-8796-hfs-mount.py --help` exposes `--firmware`, `--firmware-run`, `--fdt` and `--mkbootimg`; use explicit paths. No device dumps or firmware binaries are published here.

The historical make invocation is visible in `mac-build/_remote-build.sh`; it uses `DEVELOPMENT ARM64 MARBLE`, `RC_DARWIN_KERNEL_VERSION=22.6.0` and a legacy IIG shim. Review and adapt build paths rather than blindly executing historical runners. There is no automatic phone deployment in the source-check workflow.

## Offline checks

From this repository root:

```sh
python3 tools/check_source_tree.py
python3 -m unittest discover -s touch -p 'test_collect_marble_spi_state.py'
python3 touch/test_install_marble_touch_probe.py
clang -Wall -Wextra -Werror -fsanitize=address,undefined touch/test_marble_smmu_stream.c touch/marble_smmu_stream.c -o /tmp/marble-smmu-test
/tmp/marble-smmu-test
```

The workflow runs the remaining protocol/TRE/clock/layout C fixtures too. These are synthetic host checks, not hardware or DMA validation.

On Windows, the installer test compiles its own fake fastboot executable and uses tiny temporary payloads:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File device/classmates/Test-Install-MarbleTest.ps1
```

Do not use the real installer for CI or a device-free test. Installer source is published without its private manifest, system image, boot payload or platform-tools binaries.

## Official format 2 record and unresolved build gate

See [docs/FORMAT2-MIGRATION.md](docs/FORMAT2-MIGRATION.md) and [porting.toml](porting.toml). The official record check and source-only DTS compile pass. Target defconfig/status/tree do not resolve yet; the exact failures are saved in docs/evidence/format2-validation.json. This is not a successful whole-build report.

Three public references can be fetched/locked independently of a target profile:

```sh
python3 tools/resolve_reference_lock.py --upstream /path/to/pinned-UniXNU
```

Run that helper on Linux/macOS/WSL; Linux source filenames cannot all be checked out by native Windows Git. The resulting unixnu.lock is explicitly reference-only. It does not substitute a Linux reference for a UniXNU SoC source, and it does not select an iPadOS profile for this iPhone port. The final target fetch/lock step remains pending.

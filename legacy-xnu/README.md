# Legacy XNU source snapshot

This directory preserves the filtered v4 Marble XNU source snapshot for review and source distribution. It is a **dirty working-tree snapshot**, not a Git commit and not the exact source state of the later Stage 2 or Stage 3 touch-probe kernels.

## Snapshot identity

- Upstream: Apple OSS XNU, `https://github.com/apple-oss-distributions/xnu`
- Base revision: `1b191cb58250d0705d8a51287127505aa4bc0789`
- Dirty working-tree snapshot SHA-256: `b8b4a8b6709ee76824baab98fdf7e182162a6d960d1b6b86ec08416ccc7faefd`
- Snapshot patch: [`patches/xnu-changes.review.patch`](patches/xnu-changes.review.patch), 68 tracked source paths
- Marble overlay: [`overlay/`](overlay/), 202 untracked source files
- Source file hashes and exclusions: [`SOURCE-MANIFEST.review.json`](SOURCE-MANIFEST.review.json)

The snapshot does not record a `head_revision`; it cannot be presented as a reproducible commit or claimed to reproduce later builds. The recorded stage is older than the Stage 2/Stage 3 probe changes. The current project touch modules live outside this snapshot.

## Reconstructing the snapshot

Start with the exact XNU base revision above, apply `patches/xnu-changes.review.patch`, then copy `overlay/` into that checkout while preserving relative paths. The source tree also needs the external build inputs and toolchain described elsewhere in the project; this snapshot alone is not a build recipe or a full reproduction package.

## Licenses and source provenance

- XNU-derived source retains its file headers. The Apple Public Source License text is in [`notices/APPLE_LICENSE`](notices/APPLE_LICENSE). Review each changed file and the APSL terms before use.
- The 31 files under `overlay/bsd/pthread/` came from the pinned Apple OSS `libpthread` source `libpthread-519.120.4`, commit `c0e60fb5ecfc54cf379c261d3f9572cc22ded891`; that pin is recorded in the local upstream feed and build reports. Preserve the file notices and Apple license.
- The 76-file `overlay/bsd/marble_hfs/` import retains Apple copyright/APSL headers. The source snapshot does **not** record its exact HFS repository revision. Do not describe this group as revision-pinned.
- `overlay/libkern/crypto/marble_bearssl/` includes 29 BearSSL source/header files and the separate [`notices/BearSSL-LICENSE.txt`](notices/BearSSL-LICENSE.txt). Its exact imported source revision was not recorded in v4.
- The v4 snapshot originally recorded no blanket license for original Marble contributions; current original-code licensing is described in the top-level LICENSING.md. The top-level repository `LICENSE` applies only to original documentation. Preserve all notices; do not treat that documentation license as applying to this code.

Files in the HFS and pthread groups without their own license header are listed by exact path in [`SOURCE-REVIEW.md`](SOURCE-REVIEW.md), along with the basis and limits of their provenance. The same review note lists other missing per-file provenance and the generated-code exclusion.

## Scope and exclusions

The generated `bsd/kern/marble_ios16_cdhashes.inc` table is absent and must be regenerated from a user-provided IPSW. No IPSW, Apple binary, firmware, root filesystem, boot image, device capture, credential, or private key is included. The v4 importer recorded 51 paths excluded by policy; the export metadata records their categories and count, not the full original path list.

The historical manifest retains its original review-only status as evidence. Publication does not fill the missing upstream source pins or claim a fresh full build.

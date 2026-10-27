# File-level provenance notes

This note records specific source questions found in the v4 snapshot. It is intentionally narrower than a general project license statement.

## Files without a license header in the copied file

The following files were present in the v4 overlay and are retained there. Their lack of an inline license header is disclosed; the enclosing source collection is not assigned a new license here.

| File | Recorded provenance / reason for review |
|---|---|
| `overlay/bsd/marble_hfs/marble_hfs_compat.h` | Marble HFS portability adapter; no per-file license header. |
| `overlay/bsd/marble_hfs/marble_hfs_iokit.c` | Marble HFS I/OKit adapter; no per-file license header. |
| `overlay/bsd/marble_hfs/core/hfs_alloc_trace.h` | Marble tracing helper in the imported HFS tree; no per-file license header. |
| `overlay/bsd/marble_hfs/core/mk-root.sh` | HFS build helper; no per-file license header. |
| `overlay/bsd/pthread/marble_pthread_compat.h` | Marble pthread compatibility header; no per-file license header. |
| `overlay/bsd/pthread/marble_pthread_init.c` | Marble pthread initialization adapter; no per-file license header. |
| `overlay/bsd/pthread/marble_pthread_support.c` | Marble pthread support adapter; no per-file license header. |
| `overlay/bsd/pthread/marble_pthread_synch.c` | Marble pthread synchronization adapter; no per-file license header. |
| `overlay/bsd/pthread/marble_libpthread/kern/kern_init.c` | From the pinned Apple OSS libpthread source tree; file comment attributes Matt Wright, but this file has no Apple APSL header. Its source provenance is pinned, while the file-level licensing basis should be reviewed before downstream reuse. |

The other HFS and pthread files preserve their upstream headers; the complete Apple license text is included in `notices/APPLE_LICENSE`. This does not resolve the missing HFS revision or substitute for review of individual copyright notices.

## Imported source revision gaps

- HFS: 76 files under `overlay/bsd/marble_hfs/`; Apple copyright and APSL headers are present in the imported core, but the v4 provenance data does not identify the source repository/revision. The build must not be called reproducible from a pinned HFS source.
- BearSSL: 29 files under `overlay/libkern/crypto/marble_bearssl/`; its license is copied verbatim to `notices/BearSSL-LICENSE.txt`, but no source commit was recorded.
- libpthread: 31 files under `overlay/bsd/pthread/`; repository `apple-oss-distributions/libpthread`, tag `libpthread-519.120.4`, commit `c0e60fb5ecfc54cf379c261d3f9572cc22ded891`, as found in the local source feed/build records.

## Specific generated-file exclusion

`bsd/kern/marble_ios16_cdhashes.inc` is not included. It is generated from Apple trust-cache inputs extracted from a user-provided IPSW; the public source repository must not bundle an IPSW or extracted Apple binary. Regenerate it from a user's own input using the project exporter when reproducing that build stage.

## Snapshot review limits

The v4 provenance record lists 51 excluded paths only by policy category (`backup/trace-backup`, `before*`, compiled/binary, and generated CDHash table); it does not retain an itemized list of all those original paths. Fourteen HFS source files need byte-preserving handling because their input is non-UTF-8. Their bytes were copied unchanged into `overlay/` and are individually hashed in `SOURCE-MANIFEST.review.json`.

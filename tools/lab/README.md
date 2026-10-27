# Lab scripts

The root-level Python tools and tests are exported from the local Marble lab checkout. They resolve `ROOT` relative to their location and refer to top-level `device/` and `touch/`, so they stay at the repository root. This file indexes that layout without duplicating the scripts.

The touch collectors, protocol notes, source, and host tests are in `touch/`. Early boot and payload sources are in `device/early/`. Selected classroom installer helpers are in `device/classmates/`. This release contains source files only. Device captures, generated reports, manifests, binaries, and private collection artifacts are excluded.

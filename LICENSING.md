# Licensing and provenance

The top-level MIT license covers original Marble-authored tooling, documentation and additions where no different file notice applies. It does not relicense imported code or third-party portions embedded in patches. Existing SPDX/copyright/license headers take precedence.

| Material | Applicable notices / source |
| --- | --- |
| XNU baseline and derivative patch/overlay portions | Retained per-file notices and `legacy-xnu/notices/APPLE_LICENSE`; base revision in `legacy-xnu/README.md` |
| Imported HFS core | Retained Apple APSL and other file notices; exact imported source pin is not recorded |
| Imported libpthread | Apple OSS libpthread `libpthread-519.120.4`, commit `c0e60fb5ecfc54cf379c261d3f9572cc22ded891`; retain upstream file/repository notices |
| BearSSL subset | `legacy-xnu/notices/BearSSL-LICENSE.txt`; imported revision not recorded |
| Source files marked BSD-2-Clause-Patent | Retain their file notices; license text and upstream attribution in `LICENSES/BSD-2-Clause-Patent.txt` |
| Generated IIG C++/headers | Preserved Apple notices, exact source-input/generated hashes and public upstream CI origin in `legacy-xnu/iig/manifest.json` |
| Original install/build/verification tools and docs | MIT unless an individual file specifies otherwise |

Eight Marble adapter/helper files lack inline license headers; their original Marble-authored portions are under the top-level MIT license, while any inherited third-party portions keep their upstream terms. The pinned upstream `kern_init.c` has an author comment without a complete inline license; retain its source and repository provenance. The exact file list and remaining source-pin gaps are in `legacy-xnu/SOURCE-REVIEW.md`. These gaps are not hidden by the repository's MIT label.

No license is granted here to an iOS system image, IPSW, proprietary firmware, private backup or user data. Those are not part of this repository. The separate private test package is not uploaded with the source publication.

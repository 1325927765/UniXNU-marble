# Legacy XNU 8796 Hello observation

This record summarizes a private, temporary-boot observation and intentionally
does not include the recording, phone identifiers, system image, or device
logs. On 2026-10-26, an experimental XNU 8796 kernel booted iPhone iOS 16.7.16
(20H392) on a POCO F5/Redmi Note 12 Turbo (`marble`, SM7475 family) to the
multilingual Hello interface. The sampled screen showed a clean display and
home indicator. Setup was not completed and physical touch was not working.

The boot was temporary (`fastboot boot`); userdata and boot partitions were
not flashed. This is evidence for that historical legacy kernel only. The
published v4 XNU tree is an older dirty snapshot and does not reproduce the
tested kernel exactly; no format-2 build or format-2 device test is implied.

The local evidence inventory records the temporary image SHA-256 as
`69bd6555dde4ecc2792f2febcf6c913c0a1331318d0bc1c2d6eb1fd4c20087bd` and the
tested kernel SHA-256 as
`42f94737386b5ef850f8af5c368a3be97d0dcfcf0fa06bdd3e8a9e7ae71a2b5f`. These
hashes identify private artifacts and are included only to make the reported
observation auditable; the artifacts are not published. The tested build's
exact source tree is not preserved as a clean, pinned commit.

The public source boundary and snapshot identity are documented in
[`../../legacy-xnu/README.md`](../../legacy-xnu/README.md). In particular, the
published base is Apple XNU `1b191cb58250d0705d8a51287127505aa4bc0789`, with a
dirty source snapshot hash; it is older than the tested Stage 2 kernel.

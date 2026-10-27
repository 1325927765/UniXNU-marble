# Status — 2026-10-27

Source publication now includes the v4 XNU snapshot, touch prototypes, lab tools, metadata exporters and installer source. It is not a complete/reproducible ROM release; see BUILDING.md and legacy-xnu/SOURCE-REVIEW.md.

- Original experimental XNU 8796 kernel: real iOS 16.7.16 Hello observed again in the 2026-10-26 rollback recording; clean display, no physical touch, setup incomplete.
- New prerequisite module: the read-only snapshot completed and returned. Mode 3 stayed at Logo for six minutes; the same kernel in mode 0 stayed at Logo for five minutes.
- These runs do not prove a bad kernel or that S4 is required: the successful old kernel used a temporary S4 clock probe, while the new tests omitted that path. A same-old-kernel mode-0 control is prepared but not yet sent.
- The new kernel adds no new prerequisite class constructor; its clock-probe function body matches the old kernel. Most other byte changes fit link-address immediate changes, which is an inference rather than replayed relocation proof.
- The console quiet latch hides ordinary output after the first GUI swap. Late userspace stalls/restarts cannot be diagnosed from a Logo alone.
- Physical Goodix transport, GPI event/completion handling, verified payload/ring DMA mappings and HID input remain incomplete. A zero snapshot error mask does not establish DMA safety.
- Private classmates candidate uses a clean restore-derived root; this exact root/kernel pair is not hardware-qualified. It is not a GitHub binary release.

Wi-Fi, cellular, audio, cameras, sensors, GPU acceleration, activation and usable daily operation are not claimed.

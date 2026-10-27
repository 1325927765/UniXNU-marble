# Upstream format-2 profile and feed review

Reviewed local UniXNU upstream revision
[`0fc0fc1f9ddd0fbd4787738afef38667df5e0a95`](https://github.com/UniXNU/UniXNU/tree/0fc0fc1f9ddd0fbd4787738afef38667df5e0a95).
Its current `profiles/os` directory contains an iPadOS 17 profile, but no
iOS 16.7.16 / 20H392 profile. Its pinned [`feeds.toml`](https://github.com/UniXNU/UniXNU/blob/0fc0fc1f9ddd0fbd4787738afef38667df5e0a95/feeds.toml)
does not provide a reviewed SM7475 source feed. Historical catalog mentions,
where present, do not substitute for either an OS profile or a pinned source
feed.

Accordingly this record keeps Marble's observed legacy iOS 16.7.16 identity
separate from Format 2. No OS profile, SoC feed, resolved build, or Format-2
device verification is claimed. The concrete migration prerequisite is for
upstream to add/review the matching OS profile and SM7475 feed, then resolve
the board source pins against them.

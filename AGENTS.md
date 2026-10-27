# Marble device work

Read README.md, porting.toml, BUILDING.md, docs/FORMAT2-MIGRATION.md and
https://unixnu.com/porting/device-repository, /porting/records,
/porting/migration, /reference/components and the subsystem guide before edits.

Target only POCO F5 / Redmi Note 12 Turbo (marble, SM7475-AB), iPhone iOS
16.7.16 / 20H392. Do not replace this target with the sheng/iPadOS example.
Keep board.example=true until the matching OS/SoC profiles, full inputs and
actual resolver/build checks exist. It is a build guard, not a completion claim.

Use measured/source-backed addresses and pins, distinguish host fixtures,
legacy device observations and format 2 results, and do not invent identifiers,
firmware hashes, memory ranges or source commits. Keep system images, private
captures, credentials and local overrides out of Git. Preserve upstream notices.

Changes must update findings/evidence in each owning porting.toml area and
regenerate SOURCE-INDEX.json. Run the pinned official porting-record.py checker,
source integrity checks, relevant host fixtures and migration checks. Never
silence a failed checker, label an untested component working, or turn an old
Hello observation into proof of a new source/build. Use temporary boot only
unless a human expressly authorizes a specific partition write.

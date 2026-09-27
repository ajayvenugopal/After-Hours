# Migration history

## Initial import — 2026-09-27

Initially imported Gp Notes into Afterhours, preserving local
configuration, certificates and dependencies. The source was not a Git repository.
Initial verification found five lint errors, five warnings and two type errors.

## Publication preparation — 0.2.0

Replaced the original UI and duplicated API logic with a single workspace and
validated service/provider modules. The original build and lint failures were
addressed by the replacement. See CHANGELOG.md for behavior changes and
`docs/TESTING.md` for current verification.

The original Express spike is retained only in ignored `.legacy-prototype/` on
the maintainer's machine. Existing frontend env files and certificates remain
ignored. Live mode now requires explicit opt-in and a new workspace token; old
clinic demo keys no longer grant access. Browser data left by the prototype is
cleared on mount. No new consultation content is persisted by the application.

## App classification and naming

Gp Notes now lives at `apps/Gp Notes/`, with the Next.js application in
`Frontend/gp-notes/`. The collection catalog, commands and CI paths use the
new location. The npm package and workflow use the filesystem-friendly slug
`gp-notes`.

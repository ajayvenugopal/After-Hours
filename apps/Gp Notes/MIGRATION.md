# Migration history

The original prototype was imported into Afterhours on 2026-09-27, preserving
local configuration, dependencies and certificates. Version 0.2.0 replaced its
fragmented UI and duplicated APIs; see CHANGELOG.md.

Gp Notes now lives at `apps/Gp Notes/`, with the application in `Frontend/gp-notes/`.
The package and CI workflow use `gp-notes`. The original Express spike is kept
only in ignored `.legacy-prototype/`; environment files and certificates are ignored.

After untracked source files were removed locally, application sources were
recovered from local source maps and browser tests from the transform cache.
Configuration, service tests and documentation were restored before Git staging.
Generated caches are recovery inputs only, not repository content.

# Security and current limitations

AgentDock is experimental and is not a security sandbox. Use it only in trusted
projects, with backups, and inspect changes before committing. Provider CLIs and
project verification commands run with your user account's permissions.

## Known release risks

The source review identified these unresolved issues:

- Planner-supplied verification commands execute without an approval gate. A
  single command can still be destructive even without shell operators.
- Git-based review patches do not apply the credential exclusions used by
  non-Git snapshots. Tracked secrets or unignored credential files can enter a
  cloud review request. Do not use sensitive worktrees for cloud review.
- Claude planning/review restrictions rely on prompts and existing provider
  permissions, not an enforced read-only/tool-disabled boundary.
- Codex invocations do not currently enforce the configured timeout.
- Outside a workflow, non-Git `/diff` loses the task baseline; empty-file
  additions/deletions are also absent from snapshot diffs.

These need regression-tested fixes before claiming production readiness. Setting
a verification command yourself reduces planner-command uncertainty but does not
sandbox the project scripts it invokes.

## Private data

Never publish `.agentdock/`, legacy `.ai-task/`, `.aider*` histories, local
environment files, credentials or provider logs. Git ignore rules do not remove
already tracked files or history. Inspect staging and archive contents before
publishing. Full-screen terminal mode does not remove sensitive output from logs.

## Reporting

Do not put credentials, private source or exploitable details into public issues.
Use the hosting platform's private vulnerability-reporting feature if enabled.
The repository owner should configure a private reporting channel before release;
none is currently specified in this checkout.

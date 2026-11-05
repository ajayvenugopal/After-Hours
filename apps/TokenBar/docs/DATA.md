# Data sources and limitations

## Codex

TokenBar uses the installed Codex app or CLI and its existing sign-in through the local app-server `account/rateLimits/read` method. It does not open credential files or start a model turn to check usage. If the app server is unavailable, it reads recent session usage records and labels them as cached data.

Subscription quotas are percentages, not fixed token allowances. Codex’s cumulative session counters cannot reliably describe remaining conversation context, so TokenBar does not show that estimate for Codex.

## Claude Code

The Python bridge receives Claude Code’s status-line input. It saves only rate limits, context usage, and an observation timestamp in `~/Library/Application Support/TokenBar/claude-usage.json`, with owner-only permissions. It does not save conversation text, API keys, or session identifiers.

The installer preserves an existing status-line command and forwards its input. Commands that take longer than three seconds are skipped for that update. Reinstall the bridge if its Python interpreter moves. Project-specific status-line overrides can prevent the global bridge from running.

Claude quota data depends on what Claude Code reports for the account. An active session and response may be needed to update it. **Check reset now** rereads this data; it cannot force a live Claude account request. The account usage link provides a manual verification path.

## Resets and notifications

Quota and reset checks run every 20 seconds, plus the time needed to receive a response. Expired or stale observations are visibly marked; TokenBar does not assume that a countdown reaching zero restores quota.

A reset alert requires a newer observation, an advanced reset timestamp after the old deadline, and lower quota usage. Alerts are deduplicated. Reset notifications require macOS permission and can be switched off in settings. The last-reset banner describes a past observation, not current availability.

The manual account check considers every reported quota window: a weekly limit can still block usage when the short window has room. It verifies reported account limits, without issuing a test model request or changing the account.

## History and local capture

Usage metadata stays in `~/Library/Application Support/TokenBar/`. It includes provider/model names, token counts, timestamps, event identifiers, and reported costs when available. Prompt and response text is not persisted by TokenBar.

Native session history reads changed Codex and Claude files, bounded to 100 recent files per provider and the last 1 MB per file. This is partial observed history. Quota history covers up to 30 days, bounded to 30,000 observations. Activity scans and local server discovery run every two minutes to reduce background work.

Pace estimates require increasing usage in the same window and samples at least five minutes apart. Missing cost data stays unknown; zero cost is shown only when an event explicitly reports zero.

Ollama, LM Studio, and Gemini integrations require configuration and record observed activity, rather than subscription quota or reset limits. See the [integration guide](INTEGRATIONS.md).

## Privacy when reporting issues

Remove prompts, responses, keys, account details, and personal paths from screenshots or logs before sharing them. The `--diagnose` command reports quota metadata; review its output before posting it publicly.

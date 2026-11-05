# Codex dashboard

A local mobile-friendly Codex session dashboard with a charcoal terminal-style interface, project-grouped history, a reply composer, and approval cards.

## Run

Requires Python 3.9+, Codex, and its running shared app-server daemon.

```sh
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python server.py
```

Open http://127.0.0.1:8765. The server stays on loopback. History reads use read-only SQLite connections and saved rollouts under CODEX_HOME (default ~/.codex). Replies and approval responses use a persistent WebSocket over the existing daemon's Unix socket; the dashboard does not launch a second agent server or change approval policies.

## Features

- Search session titles and projects, including archived sessions.
- Sessions open at the latest message. New messages follow the bottom unless you scroll up; Jump to latest returns to it.
- Enter sends a reply; Shift+Enter inserts a newline. Drafts are kept in memory when switching sessions.
- Replies resume the existing thread, start a turn when idle, or steer its active turn.
- Command and file-change approvals have approve-once and decline buttons. Permission grants are limited to the requested permissions for the current turn.
- Codex user-input requests show question options and text fields.
- The dashboard subscribes to threads loaded in the shared daemon and to sessions you open. Pending requests appear in the relevant session, with a Needs you marker in the sidebar.
- Data refreshes every 2.5 seconds while the page is visible. Explicit Refresh also reloads the session list.

## Tailscale SSH

Run the dashboard on the Mac holding your Codex sessions. On your viewing device use an SSH client with local forwarding:

```sh
ssh -N -L 8765:127.0.0.1:8765 YOUR_USER@YOUR_MAC_TAILSCALE_HOSTNAME
```

Open http://127.0.0.1:8765 on that device while the tunnel stays active. SSH and Tailscale must already be configured. A phone browser cannot establish SSH itself; a mobile SSH client must maintain the tunnel.

The app trusts the SSH tunnel and local machine. It validates the Host header and requires a same-origin request token for writes. Additional exact Host values can be configured with comma-separated DASHBOARD_ALLOWED_HOSTS if using a private reverse proxy. Do not expose this service publicly.

## Scope and limits

Supports approval and question requests delivered by the shared Codex app-server. It cannot answer arbitrary shell-program stdin prompts, OS dialogs, or prompts owned by a separate Codex process. Unsupported request types explicitly direct you to the original client; no request is automatically approved. Approvals already resolved in another client disappear. Archived sessions need to be unarchived in Codex before replying.

History includes saved user and assistant text; images are placeholders. Tool output and internal reasoning are not shown in history. Filesystem history formats and the experimental app-server transport may change with Codex releases. Cloud-only sessions are not automatically included. Remote phone access remains unverified.

## Validation

```sh
.venv/bin/python -m unittest -v
```

Tests cover idle versus active reply routing, approval decisions, stale requests, allowed decisions, permission scope, and user answers. The live daemon connection and HTTP endpoints were checked; the desktop UI was visually inspected. No test prompt was sent into an existing conversation.

## Direct Tailscale IP access

To listen on both localhost and this Mac's Tailscale interface:

```sh
DASHBOARD_TAILSCALE_IP=YOUR_TAILSCALE_IP .venv/bin/python server.py
```

Connect your phone to Tailscale and open http://YOUR_TAILSCALE_IP:8765. Access follows your tailnet network policy; permitted devices can read history, reply, and respond to approvals. The service binds only to localhost and the specified Tailscale address. The Mac must remain awake with the server running. Verify access from a second device on your tailnet.

## Project status and license

Experimental. Browser approval control has not been verified end to end for terminal-owned sessions; a connected daemon does not guarantee that every terminal prompt is available. This is an independent tool, not an official OpenAI product. Licensed under the repository MIT license.

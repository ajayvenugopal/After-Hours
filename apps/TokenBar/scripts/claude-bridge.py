#!/usr/bin/env python3
"""Capture only usage fields from Claude Code's documented status-line input."""
import datetime
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile


def write_snapshot(payload, directory):
    snapshot = {key: payload[key] for key in ('rate_limits', 'context_window') if key in payload}
    snapshot['updated_at'] = datetime.datetime.now(datetime.timezone.utc).isoformat()
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, temporary = tempfile.mkstemp(prefix='.usage-', dir=directory)
    try:
        with os.fdopen(fd, 'w') as stream:
            json.dump(snapshot, stream, allow_nan=False)
        os.replace(temporary, directory / 'claude-usage.json')
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def main():
    raw = sys.stdin.read(2 * 1024 * 1024)
    directory = Path.home() / 'Library/Application Support/TokenBar'
    try:
        payload = json.loads(raw)
        if not isinstance(payload, dict):
            return
        write_snapshot(payload, directory)
    except (ValueError, OSError):
        return
    # Keep the user's existing status line, including its original stdin.
    try:
        config = json.loads((directory / 'bridge-config.json').read_text())
        previous = config.get('previous_status_line') or {}
        command = previous.get('command')
        if command:
            result = subprocess.run(command, shell=True, input=raw, text=True,
                                    capture_output=True, timeout=3)
            sys.stdout.write(result.stdout)
            return
    except (ValueError, OSError, subprocess.TimeoutExpired):
        pass
    windows = payload.get('rate_limits') or {}
    window = windows.get('five_hour') or {}
    value = window.get('used_percentage')
    if isinstance(value, (float, int)):
        print(f'Claude {max(0, min(100, 100-value)):.0f}% left')
    else:
        print('TokenBar connected')


if __name__ == '__main__':
    main()

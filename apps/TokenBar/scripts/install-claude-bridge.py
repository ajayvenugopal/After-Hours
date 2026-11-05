#!/usr/bin/env python3
"""Install/uninstall the usage bridge, preserving an existing Claude status line."""
import argparse
import json
import os
from pathlib import Path
import shlex
import shutil
import sys
import tempfile


def atomic_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp = tempfile.mkstemp(prefix='.tokenbar-', dir=path.parent)
    try:
        with os.fdopen(fd, 'w') as stream:
            json.dump(value, stream, indent=2)
            stream.write('\n')
        os.replace(temp, path)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


def install(home, uninstall=False):
    directory = home / 'Library/Application Support/TokenBar'
    settings_path = home / '.claude/settings.json'
    settings = json.loads(settings_path.read_text()) if settings_path.exists() else {}
    if not isinstance(settings, dict):
        raise ValueError('Claude settings must be a JSON object')
    config_path = directory / 'bridge-config.json'
    config = json.loads(config_path.read_text()) if config_path.exists() else {}
    target = directory / 'claude-bridge.py'
    command = shlex.quote(sys.executable) + ' ' + shlex.quote(str(target))
    current = settings.get('statusLine')
    managed = isinstance(current, dict) and current.get('command') == config.get('installed_command')
    if uninstall:
        if not managed:
            print('Current status line is not managed by TokenBar; left unchanged.')
            return
        previous = config.get('previous_status_line')
        if previous is None:
            settings.pop('statusLine', None)
        else:
            settings['statusLine'] = previous
        atomic_json(settings_path, settings)
        print('Restored your previous Claude status line.')
        return
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    if not managed:
        if current is not None and (not isinstance(current, dict) or current.get('type') != 'command'):
            raise ValueError('Unrecognized statusLine format; no settings were changed')
        config = {'previous_status_line': current}
    config['installed_command'] = command
    shutil.copyfile(Path(__file__).with_name('claude-bridge.py'), target)
    os.chmod(target, 0o700)
    atomic_json(config_path, config)
    status = dict(current) if isinstance(current, dict) else {}
    status.update(type='command', command=command)
    settings['statusLine'] = status
    atomic_json(settings_path, settings)
    print('TokenBar connected. Start or restart Claude Code and send a prompt to populate usage.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--uninstall', action='store_true')
    args = parser.parse_args()
    try:
        install(Path.home(), args.uninstall)
    except (ValueError, OSError) as error:
        sys.exit(f'Could not update Claude settings: {error}')

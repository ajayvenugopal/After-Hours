#!/usr/bin/env python3
"""Install the CLI as an isolated user tool; no shell activation or sudo needed."""
import argparse
import os
from pathlib import Path
import shutil
import subprocess
import sys


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--editable", action="store_true",
                        help="use this checkout directly for development")
    args = parser.parse_args()
    uv = shutil.which("uv")
    if not uv:
        parser.exit(1, "Install uv first (on macOS: brew install uv), then rerun this installer.\n")
    source = Path(__file__).resolve().parents[1]
    argv = [uv, "tool", "install", "--python", "3.12", "--reinstall", "--force"]
    if args.editable:
        argv.append("--editable")
    argv.append(str(source))
    print("Installing AgentDock into an isolated user environment…", flush=True)
    subprocess.run(argv, check=True)
    result = subprocess.run([uv, "tool", "dir", "--bin"], check=True,
                            stdout=subprocess.PIPE, text=True)
    bin_dir = Path(result.stdout.strip())
    paths = {Path(p).expanduser().resolve() for p in os.get_exec_path() if p}
    if bin_dir.resolve() not in paths:
        print("Adding the tool directory to your shell PATH…", flush=True)
        subprocess.run([uv, "tool", "update-shell"], check=True)
        print("Open a new terminal to use the updated PATH.")
    for command in ("agentdock",):
        subprocess.run([str(bin_dir / command), "--help"], check=True,
                       stdout=subprocess.DEVNULL)
    print("Installed. In any project directory, run: agentdock")
    print("No virtual-environment activation is needed.")


if __name__ == "__main__":
    try:
        main()
    except (OSError, subprocess.CalledProcessError) as exc:
        print(f"Installation failed: {exc}", file=sys.stderr)
        sys.exit(1)

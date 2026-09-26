#!/usr/bin/env python3
"""Check release contents without extracting or executing archive members."""
import argparse
from pathlib import Path, PurePosixPath
import sys
import tarfile
import zipfile


PRIVATE_PARTS = {".git", ".agentdock", ".ai-task", ".venv", ".idea", ".vscode",
                 "__pycache__", "build", "dist", "ai_task", "node_modules"}
SECRET_SUFFIXES = {".pem", ".key", ".keystore", ".jks", ".log", ".pyc", ".pyo"}


def inspect_archive(path):
    if path.name.endswith(".whl"):
        with zipfile.ZipFile(path) as archive:
            names = archive.namelist()
        source = False
    elif path.name.endswith(".tar.gz"):
        with tarfile.open(path, "r:gz") as archive:
            members = archive.getmembers()
            if any(member.issym() or member.islnk() for member in members):
                raise ValueError(f"{path.name}: unexpected archive links")
            names = [member.name for member in members]
        source = True
    else:
        raise ValueError(f"Unexpected distribution: {path.name}")
    normalized = []
    for name in names:
        member = PurePosixPath(name)
        if member.is_absolute() or ".." in member.parts:
            raise ValueError(f"Unsafe archive path: {name}")
        if any(part in PRIVATE_PARTS or part.startswith((".aider", ".env"))
               or part == ".DS_Store" for part in member.parts):
            raise ValueError(f"Private/generated file in release: {name}")
        if member.suffix in SECRET_SUFFIXES:
            raise ValueError(f"Unexpected sensitive/generated file: {name}")
        normalized.append("/".join(member.parts[1:]) if source else name)
    required = {"src/agentdock/cli.py", "scripts/install.py", "scripts/check_release.py",
                "README.md", "LICENSE", "SECURITY.md", "docs/assets/agentdock-overview.svg",
                "docs/assets/agentdock-title.png"} if source else {"agentdock/cli.py", "agentdock/__main__.py"}
    missing = required - set(normalized)
    if missing:
        raise ValueError(f"{path.name}: missing {', '.join(sorted(missing))}")
    if not any(PurePosixPath(name).name == "LICENSE" for name in normalized):
        raise ValueError(f"{path.name}: missing license")
    if not source:
        with zipfile.ZipFile(path) as archive:
            entries = [name for name in names if name.endswith(".dist-info/entry_points.txt")]
            if len(entries) != 1:
                raise ValueError("Expected one entry-point metadata file")
            entry_text = archive.read(entries[0]).decode()
            if "agentdock = agentdock.cli:agentdock_main" not in entry_text or "ai-task =" in entry_text or "ai-chat =" in entry_text:
                raise ValueError("Incorrect console entry points")
    return len(names)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", nargs="?", type=Path, default=Path("dist"))
    args = parser.parse_args()
    archives = sorted(args.directory.glob("*.whl")) + sorted(args.directory.glob("*.tar.gz"))
    if len(archives) != 2 or not any(p.suffix == ".whl" for p in archives):
        parser.error("Expected exactly one wheel and one source archive; use a fresh output directory.")
    for archive in archives:
        print(f"OK {archive.name}: {inspect_archive(archive)} members checked")


if __name__ == "__main__":
    try:
        main()
    except (ValueError, OSError, tarfile.TarError, zipfile.BadZipFile) as exc:
        print(f"Release check failed: {exc}", file=sys.stderr)
        sys.exit(1)

#!/usr/bin/env python3
"""Package the public source using an explicit allowlist, without local agent data."""
from pathlib import Path
import tarfile

ROOT = Path(__file__).resolve().parents[1]
ENTRIES = (".gitignore", ".github", "Package.swift", "README.md", "LICENSE", "CONTRIBUTING.md",
           "Sources", "Tests", "Resources", "scripts", "docs")


def public_metadata(info):
    info.uid = info.gid = 0
    info.uname = info.gname = ""
    return info


def main():
    destination = ROOT / "dist" / "TokenBar-source.tar.gz"
    destination.parent.mkdir(exist_ok=True)
    with tarfile.open(destination, "w:gz") as archive:
        for entry in ENTRIES:
            root = ROOT / entry
            paths = sorted(root.rglob("*")) if root.is_dir() else [root]
            for path in paths:
                if path.is_symlink() or not path.is_file():
                    continue
                if "AppIcon.iconset" in path.parts or path.relative_to(ROOT).as_posix() == "Resources/AppIcon.png":
                    continue
                if "__pycache__" in path.parts or path.name == ".DS_Store" or path.name.startswith(".env"):
                    continue
                if path.suffix in (".pyc", ".pyo", ".pem", ".p12", ".mobileprovision"):
                    continue
                archive.add(path, arcname="TokenBar/" + path.relative_to(ROOT).as_posix(), recursive=False, filter=public_metadata)
    print(destination)


if __name__ == "__main__":
    main()

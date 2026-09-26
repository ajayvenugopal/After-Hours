"""Review diffs for projects without a Git baseline."""
import difflib
import os
from contextvars import ContextVar
from pathlib import Path


BASELINE = ContextVar("file_baseline", default=None)
EXCLUDED = {".git", ".agentdock", ".ai-task", ".venv", "venv", "node_modules", "__pycache__", ".gradle", "build", "dist", ".idea"}


def is_tool_artifact(name: str) -> bool:
    return any(part in {".agentdock", ".ai-task"} or part.startswith(".aider") or part == ".DS_Store"
               for part in Path(name).parts)


def snapshot(root: Path) -> dict:
    result = {}
    for directory, folders, files in os.walk(root, followlinks=False):
        folders[:] = [name for name in folders if name not in EXCLUDED and not is_tool_artifact(name) and not Path(directory, name).is_symlink()]
        for name in files:
            path = Path(directory, name)
            if path.is_symlink() or is_tool_artifact(name):
                continue
            # Never include common credential files in fallback reviews.
            if name.startswith(".env") or name.endswith((".pem", ".key", ".keystore", ".jks")):
                continue
            if path.stat().st_size > 2_000_000:
                continue
            data = path.read_bytes()
            if b"\0" in data:
                continue
            try:
                result[path.relative_to(root).as_posix()] = data.decode("utf-8")
            except UnicodeDecodeError:
                continue
    return result


def file_diff(root: Path) -> str:
    before = BASELINE.get() or {}
    after = snapshot(root)
    return diff_snapshots(before, after)


def diff_snapshots(before: dict, after: dict) -> str:
    pieces = []
    for name in sorted(before.keys() | after.keys()):
        if before.get(name) == after.get(name):
            continue
        lines = difflib.unified_diff(
            before.get(name, "").splitlines(keepends=True),
            after.get(name, "").splitlines(keepends=True),
            fromfile="a/" + name if name in before else "/dev/null",
            tofile="b/" + name if name in after else "/dev/null",
        )
        for line in lines:
            pieces.append(line if line.endswith("\n") else line + "\n\\ No newline at end of file\n")
    return "".join(pieces)

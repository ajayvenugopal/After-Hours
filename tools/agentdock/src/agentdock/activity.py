"""Local activity journals and a read-only terminal dashboard (no model calls)."""
from __future__ import annotations

import curses
import errno
import fcntl
import json
import os
import re
import pty
import select
import signal
import sys
import termios
import time
import tty
import uuid
from pathlib import Path
from typing import Any


class Activity:
    def __init__(self, state: Path, agent: str, command: str):
        directory = state / "activity"
        directory.mkdir(parents=True, exist_ok=True)
        identifier = uuid.uuid4().hex
        self.path = directory / (identifier + ".json")
        self.output = directory / (identifier + ".log")
        self.data = dict(agent=agent, command=command, status="running",
                         started=time.time(), owner_pid=os.getpid(), log=self.output.name)
        self.stream = self.output.open("ab", buffering=0)
        self._save()

    def _save(self) -> None:
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(json.dumps(self.data), encoding="utf-8")
        temporary.replace(self.path)

    def write(self, data: bytes) -> None:
        self.stream.write(data)

    def finish(self, status: str, code: int | None = None) -> None:
        self.stream.close()
        self.data.update(status=status, exit_code=code, finished=time.time())
        self._save()


def capture_native(argv: list[str], repo: Path, env: dict[str, str], activity: Activity) -> int:
    """Mirror a native CLI through a PTY; the journal is strictly an output sink."""
    input_fd, output_fd = sys.stdin.fileno(), sys.stdout.fileno()
    original = termios.tcgetattr(input_fd)
    old_resize = signal.getsignal(signal.SIGWINCH)
    pid, master = pty.fork()
    if pid == 0:
        try:
            os.chdir(repo)
            os.execvpe(argv[0], argv, env)
        except BaseException as exc:
            os.write(2, f"Could not start {argv[0]}: {exc}\n".encode())
            os._exit(127)

    def resize(*_: Any) -> None:
        try:
            size = fcntl.ioctl(input_fd, termios.TIOCGWINSZ, b"\0" * 8)
            fcntl.ioctl(master, termios.TIOCSWINSZ, size)
        except OSError:
            pass

    def write_all(fd: int, data: bytes) -> None:
        while data:
            count = os.write(fd, data)
            data = data[count:]

    completed = False
    try:
        resize()
        signal.signal(signal.SIGWINCH, resize)
        tty.setraw(input_fd)
        inputs = [master, input_fd]
        while True:
            ready, _, _ = select.select(inputs, [], [])
            if master in ready:
                try:
                    block = os.read(master, 16384)
                except OSError as exc:
                    if exc.errno != errno.EIO:
                        raise
                    block = b""
                if not block:
                    break
                activity.write(block)
                write_all(output_fd, block)
            if input_fd in ready:
                block = os.read(input_fd, 4096)
                if not block:
                    inputs.remove(input_fd)
                    block = b"\x04"
                write_all(master, block)
        _, status = os.waitpid(pid, 0)
        completed = True
        code = os.waitstatus_to_exitcode(status)
        activity.finish("completed" if code == 0 else "failed", code)
        return code
    finally:
        termios.tcsetattr(input_fd, termios.TCSADRAIN, original)
        signal.signal(signal.SIGWINCH, old_resize)
        os.close(master)
        if not completed:
            try:
                os.killpg(pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            os.waitpid(pid, 0)
            activity.finish("interrupted")


def plain_text(text: str) -> str:
    # Strip OSC (including terminal hyperlinks), CSI and other escape sequences.
    text = re.sub(r"\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)", "", text)
    text = re.sub(r"\x1b\[[0-?]*[ -/]*[@-~]|\x1b[@-_]", "", text)
    return "".join(c for c in text.replace("\r\n", "\n").replace("\r", "\n") if c in "\n\t" or c.isprintable())


def read_activities(state: Path) -> list[dict[str, Any]]:
    records = []
    for path in (state / "activity").glob("*.json"):
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(record, dict) or not isinstance(record.get("agent"), str):
                continue
            record["started"] = float(record.get("started", 0))
            if record.get("status") == "running":
                try:
                    os.kill(int(record["owner_pid"]), 0)
                except ProcessLookupError:
                    record["status"] = "interrupted"
                except PermissionError:
                    pass
            # Derive the log path locally; never follow a path in journal metadata.
            with path.with_suffix(".log").open("rb") as stream:
                stream.seek(0, 2)
                stream.seek(max(0, stream.tell() - 16384))
                record["text"] = plain_text(stream.read().decode("utf-8", errors="replace"))
            records.append(record)
        except (OSError, ValueError, TypeError, KeyError):
            continue
    return sorted(records, key=lambda item: float(item.get("started", 0)), reverse=True)


def dashboard(state: Path, agent_names: list[str], *, once: bool = False) -> None:
    if once:
        for record in read_activities(state):
            print(f"{record['agent']} · {record['status']}\n{record['text'][-3000:]}\n")
        return
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        raise ValueError("Live views need a terminal. Use agentdock watch --once for a text snapshot.")

    def draw(screen: Any) -> None:
        try:
            curses.curs_set(0)
        except curses.error:
            pass
        screen.timeout(250)
        page = 0

        def put(y: int, x: int, text: str, width: int, attr: int = 0) -> None:
            try:
                screen.addnstr(y, x, plain_text(text).replace("\n", " "), max(0, width), attr)
            except curses.error:
                pass

        while True:
            records = read_activities(state)
            # One pane per agent; show every active invocation, otherwise its latest result.
            panes = []
            names = list(dict.fromkeys(agent_names + [r["agent"] for r in records]))
            for name in names:
                matches = [r for r in records if r["agent"] == name]
                active = [r for r in matches if r["status"] == "running"]
                panes.extend(active or matches[:1] or [dict(agent=name, status="idle", text="Waiting for activity…")])
            panes.sort(key=lambda pane: pane["status"] != "running")
            height, width = screen.getmaxyx()
            screen.erase()
            columns = 2 if width >= 100 else 1
            rows = max(1, (height - 3) // 9)
            capacity = rows * columns
            pages = max(1, (len(panes) + capacity - 1) // capacity)
            page = min(page, pages - 1)
            put(0, 0, f"AgentDock · READ ONLY · page {page + 1}/{pages} · q close · ←/→ pages", width - 1, curses.A_BOLD)
            put(1, 0, "Live process output; no input is sent to agents. Provider buffering may delay output.", width - 1)
            cell_height = max(1, (height - 3) // rows)
            cell_width = max(1, width // columns)
            for index, pane in enumerate(panes[page * capacity:(page + 1) * capacity]):
                y = 3 + (index // columns) * cell_height
                x = (index % columns) * cell_width
                put(y, x, f"─ {pane['agent']} [{pane['status']}] " + "─" * cell_width, cell_width - 2, curses.A_BOLD)
                lines = pane["text"].expandtabs(4).splitlines()
                available = max(0, cell_height - 2)
                for offset, line in enumerate(lines[-available:] if available else []):
                    put(y + offset + 1, x, line, cell_width - 2)
            screen.refresh()
            key = screen.getch()
            if key in (ord("q"), 27):
                return
            if key in (curses.KEY_RIGHT, ord("n")):
                page = (page + 1) % pages
            if key in (curses.KEY_LEFT, ord("p")):
                page = (page - 1) % pages

    try:
        curses.wrapper(draw)
    except curses.error as exc:
        raise ValueError("Could not open terminal views. Check TERM, or use agentdock watch --once.") from exc

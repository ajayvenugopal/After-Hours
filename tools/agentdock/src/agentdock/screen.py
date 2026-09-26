"""Optional alternate-screen presentation; never changes terminal profiles."""
import os
import sys
from contextlib import contextmanager

from . import ui

_active = None


def paint_prompt(text):
    # readline writes directly to the terminal, bypassing our Python stream.
    if _active:
        return _active.base + text.replace("\033[0m", "\033[0m" + _active.base)
    return text


class PaintedStream:
    def __init__(self, stream, base):
        self.stream = stream
        self.base = base

    def write(self, text):
        self.stream.write(text.replace("\033[0m", "\033[0m" + self.base))
        return len(text)

    def __getattr__(self, name):
        return getattr(self.stream, name)


class Screen:
    def __init__(self):
        self.stdout, self.stderr = sys.stdout, sys.stderr
        if os.environ.get("COLORTERM", "").lower() in {"truecolor", "24bit"}:
            self.base = "\033[48;2;16;18;25m\033[38;2;230;225;239m"
        elif "256color" in os.environ.get("TERM", ""):
            self.base = "\033[48;5;233m\033[38;5;253m"
        else:
            self.base = "\033[40m\033[37m"

    def enter(self):
        self.stdout.write("\033[?1049h" + self.base + "\033[2J\033[H")
        self.stdout.flush()
        sys.stdout = PaintedStream(self.stdout, self.base)
        if self.stderr.isatty():
            sys.stderr = PaintedStream(self.stderr, self.base)

    def leave(self):
        sys.stdout, sys.stderr = self.stdout, self.stderr
        self.stdout.write("\033[0m\033[?25h\033[?1049l")
        self.stdout.flush()


@contextmanager
def fullscreen(enabled=False):
    global _active
    supported = (enabled and sys.stdin.isatty() and sys.stdout.isatty()
                 and os.environ.get("TERM", "") not in {"", "dumb"}
                 and "NO_COLOR" not in os.environ and ui.theme != "mono")
    if not supported:
        yield
        return
    screen = Screen()
    try:
        screen.enter()
        _active = screen
        yield
    finally:
        _active = None
        screen.leave()


@contextmanager
def suspend():
    """Let native agents and curses dashboards own their terminal screen."""
    screen = _active
    if screen:
        screen.leave()
    try:
        yield
    finally:
        if screen:
            screen.enter()

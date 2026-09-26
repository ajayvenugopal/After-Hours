"""Compact Aider progress: narration and edit receipts, without source dumps."""
from .activity import plain_text
from .ui import styled
import os
import shutil
import threading
import time


class ElapsedTimer:
    """One live status line; serialized with provider output to avoid overwriting it."""
    def __init__(self, stream, label):
        self.stream = stream
        self.label = plain_text(label)
        self.started = time.monotonic()
        self.tty = stream.isatty() and os.environ.get("TERM") != "dumb"
        self.lock = threading.Lock()
        self.stopped = threading.Event()
        self.thread = None
        self.visible = False
        self.partial = False
        self.last_report = 0

    def elapsed(self):
        seconds = int(time.monotonic() - self.started)
        return f"{seconds // 60:02d}:{seconds % 60:02d}"

    def clear(self):
        if self.visible:
            self.stream.write("\r\033[2K")
            self.visible = False

    def tick(self):
        with self.lock:
            seconds = int(time.monotonic() - self.started)
            if self.partial:
                return
            if self.tty:
                spinner = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"[int((time.monotonic() - self.started) * 4) % 10]
                width = max(1, shutil.get_terminal_size((80, 24)).columns - 1)
                self.clear()
                self.stream.write(styled(f"  {spinner} {self.label} · Working… {self.elapsed()}"[:width], stream=self.stream))
                self.visible = True
                self.stream.flush()
            elif seconds - self.last_report >= 15:
                self.stream.write(f"[{self.label}] Working… {self.elapsed()}\n")
                self.stream.flush()
                self.last_report = seconds

    def write(self, text):
        with self.lock:
            self.clear()
            self.stream.write(text)
            self.stream.flush()
            if text:
                self.partial = not text.endswith("\n")

    def start(self):
        self.tick()
        def animate():
            while not self.stopped.wait(.25):
                self.tick()
        self.thread = threading.Thread(target=animate, daemon=True)
        self.thread.start()

    def stop(self, outcome="completed"):
        self.stopped.set()
        if self.thread:
            self.thread.join()
        with self.lock:
            self.clear()
            if self.tty:
                if self.partial:
                    self.stream.write("\n")
                self.stream.write(f"[{self.label}] {outcome} · {self.elapsed()}\n")
                self.stream.flush()

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, kind, value, traceback):
        self.stop("interrupted" if kind is KeyboardInterrupt else "failed" if kind else "completed")


class LocalProgress:
    def __init__(self, emit):
        self.emit = emit
        self.pending = ""
        self.fence = False

    def feed(self, text):
        self.pending += text
        while "\n" in self.pending:
            line, self.pending = self.pending.split("\n", 1)
            self.line(line)
        # Never retain an unlimited line from a provider.
        if len(self.pending) > 8192:
            self.pending = ""

    def line(self, text):
        text = plain_text(text).strip()
        if text.startswith(("```", "~~~")):
            self.fence = not self.fence
            return
        if self.fence:
            return
        if text.startswith(("I'll ", "I’ll ", "I'm ", "I’m ", "I will ",
                            "Let me ", "Applied edit to ", "Checking ", "Creating ",
                            "Updating ", "Fixing ", "Error:", "ERROR:", "Warning:")):
            self.emit(text[:400])

    def finish(self):
        if self.pending:
            self.line(self.pending)
        self.pending = ""

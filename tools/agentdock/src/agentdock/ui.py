"""Small terminal presentation layer; no dependency or terminal takeover."""
import os
import shutil
import sys
import textwrap
import re
import unicodedata

THEMES = {"violet": "\033[95m", "amber": "\033[33m", "mono": ""}
theme = "violet"


def violet_styles():
    """Banner palette, with fallbacks for terminals without true color."""
    if os.environ.get("COLORTERM", "").lower() in {"truecolor", "24bit"}:
        return {"accent": "\033[38;2;196;181;253m",
                "muted": "\033[38;2;170;166;187m",
                "bold": "\033[1;38;2;245;243;255m"}
    if "256color" in os.environ.get("TERM", ""):
        return {"accent": "\033[38;5;183m", "muted": "\033[38;5;145m",
                "bold": "\033[1;38;5;189m"}
    return {"accent": THEMES["violet"], "muted": "\033[2m", "bold": "\033[1m"}


def columns():
    return max(12, min(96, shutil.get_terminal_size((80, 24)).columns - 2))


def display_width(text):
    return sum(0 if unicodedata.combining(c) else 2 if unicodedata.east_asian_width(c) in {"W", "F"} else 1 for c in text)


def wrap_cells(text, width):
    lines, current, size = [], "", 0
    for char in text:
        cells = display_width(char)
        if size + cells > width and current:
            lines.append(current)
            current, size = "", 0
        current += char
        size += cells
    return lines + [current]


def section(title, detail=""):
    print("\n  " + styled(title, "bold") + (styled("  ·  " + detail, "muted") if detail else ""))
    print(styled("  " + "─" * max(8, columns() - 2), "muted"))


def welcome(project, mode, output, agents):
    if not sys.stdout.isatty():
        panel("AgentDock", [f"Project: {project}", f"Mode: {mode}", *[f"{role}: {name} · {model}" for role, name, model in agents]])
        return
    print()
    print(styled("  ╭─◈─╮ ", "accent") + styled("AgentDock", "bold") + styled("   /   your coding workspace", "muted"))
    print(styled("    Cloud judgment. Local execution.", "muted"))
    panel("WORKSPACE", [f"{project}", "", f"{mode.upper()} MODE   ·   {output} output", "",
                        *[f"{role:<7} {name}  ·  {model}" for role, name, model in agents]])
    if mode == "build":
        print("  " + styled("Ready to build", "bold") + styled(" — describe the change you want to make.", "muted"))
        print(styled("  Planning → implementation → review → final verification", "muted"))
    else:
        print("  " + styled("Ready to chat", "bold") + styled(" — ask a question, or /build to switch modes.", "muted"))
    print()
    print("  " + styled("/workflow setup") + styled("  configure stages    ", "muted") + styled("/agents") + styled("  your team", "muted"))
    print("  " + styled("/views") + styled("           watch activity      ", "muted") + styled("/help") + styled("    all commands", "muted"))
    print(styled("\n  Tab to complete · /chat or /build to switch · /theme to personalize", "muted"))
    print()


def styled(text, style="accent", stream=None):
    stream = sys.stdout if stream is None else stream
    if not stream.isatty() or "NO_COLOR" in os.environ or os.environ.get("TERM") == "dumb" or theme == "mono":
        return text
    palette = {"accent": THEMES[theme], "muted": "\033[2m", "bold": "\033[1m",
               "added": "\033[32m", "removed": "\033[31m"}
    if theme == "violet":
        palette.update(violet_styles())
    code = palette.get(style, "")
    return code + text + "\033[0m" if code else text


def panel_line(text):
    """Paint only printed panel cells; reset before the newline, never use OSC."""
    if not sys.stdout.isatty() or "NO_COLOR" in os.environ or os.environ.get("TERM") == "dumb" or theme == "mono":
        return text
    if os.environ.get("COLORTERM", "").lower() in {"truecolor", "24bit"}:
        base = "\033[48;2;16;18;25m\033[38;2;230;225;239m"
    elif "256color" in os.environ.get("TERM", ""):
        base = "\033[48;5;233m\033[38;5;253m"
    else:
        base = "\033[40m\033[37m"
    return base + text.replace("\033[0m", "\033[0m" + base) + "\033[0m"


def panel(title, lines):
    if not sys.stdout.isatty():
        print(title)
        print("\n".join(lines))
        return
    width = columns()
    inner = width - 4
    print()
    print(panel_line(styled("╭" + "─" * (width - 2) + "╮", "muted")))
    for index, line in enumerate([title, "", *lines]):
        for chunk in wrap_cells(line, inner):
            body = styled(chunk, "accent" if index == 0 else "bold" if chunk.startswith(("PLAN ", "CODE ", "REVIEW ", "CHAT ")) else "")
            print(panel_line(styled("│ ", "muted") + body + " " * max(0, inner - display_width(chunk)) + styled(" │", "muted")))
    print(panel_line(styled("╰" + "─" * (width - 2) + "╯", "muted")))
    print()


def event(symbol, label, message):
    if not sys.stdout.isatty():
        print(f"[{label}] {message}" if label else f"{symbol} {message}", flush=True)
        return
    if message in {"Planning...", "Implementing...", "Reviewing...", "Applying review...", "Final verification..."}:
        section(message.rstrip("."), label)
        return
    prefix = styled(f"  {symbol}")
    if label:
        prefix += " " + styled(label, "bold") + styled(" · ", "muted")
    else:
        prefix += " "
    print(prefix + message, flush=True)


def response(name, text):
    if not sys.stdout.isatty():
        print(f"\n{name}\n{text}\n")
        return
    width = columns()
    section(name, "response")
    fence = False
    for line in text.splitlines():
        if line.strip().startswith("```"):
            fence = not fence
            print(styled("  ┌ " + (line.strip()[3:] or "code"), "muted") if fence else styled("  └ " + "─" * 12, "muted"))
        elif fence:
            print(styled("  │ ", "muted") + line)
        elif line.startswith("#"):
            print("  " + styled(line.lstrip("# "), "bold"))
        else:
            if not line:
                print()
                continue
            for wrapped in textwrap.wrap(line, width=max(8, width - 4), subsequent_indent="  "):
                parts = re.split(r"(\*\*[^*]+\*\*|`[^`]+`)", wrapped)
                formatted = "".join(styled(part[2:-2], "bold") if part.startswith("**") else styled(part[1:-1]) if part.startswith("`") else part for part in parts)
                print("  " + formatted)
    print()


def show_diff(patch, *, limit=None):
    if not patch:
        return
    lines = patch.splitlines()
    added = sum(line.startswith("+") and not line.startswith("+++") for line in lines)
    removed = sum(line.startswith("-") and not line.startswith("---") for line in lines)
    if sys.stdout.isatty():
        section("File changes", f"+{added} added  /  −{removed} removed")
    else:
        print("\nFile changes")
    for line in lines if limit is None else lines[:limit]:
        if line.startswith(("--- ", "+++ ", "diff --git")):
            style = "bold"
        elif line.startswith("@@"):
            style = "accent"
        elif line.startswith("+"):
            style = "added"
        elif line.startswith("-"):
            style = "removed"
        else:
            style = "muted"
        print(styled(line, style))
    if limit is not None and len(lines) > limit:
        print(styled(f"  … {len(lines) - limit} more lines. Use /diff for the full workflow diff.", "muted"))
    print()

"""Shared terminal UI: a rich/questionary front-end with graceful fallbacks.

When `rich` and `questionary` are available and we're on a real terminal, the
menu is an arrow-key list with a rounded gold banner (black-gold synthwave
palette). Otherwise everything degrades to plain numbered prompts / ANSI text,
so the tool still works over pipes, dumb terminals, or without the extra deps.
"""

import os
import sys
import ctypes

# --- palette (black-gold synthwave; gold is the single accent) -----------
GOLD = "#F5C542"
MAGENTA = "#FF2E97"
CYAN = "#36F1CD"
TEXT = "#E8E6F0"
GREY = "#6E6A86"
ERRC = "#FF5370"

try:
    from rich.console import Console
    from rich.panel import Panel
    from rich.text import Text
    from rich import box
    _console = Console()
    HAVE_RICH = True
except ImportError:
    _console = None
    HAVE_RICH = False

try:
    import questionary
    from questionary import Choice, Separator, Style
    HAVE_QUESTIONARY = True
    _QSTYLE = Style([
        ("qmark", f"fg:{GOLD} bold"),
        ("question", f"fg:{TEXT} bold"),
        ("pointer", f"fg:{GOLD} bold"),
        ("highlighted", f"fg:#0D0B1E bg:{GOLD} bold"),
        ("selected", f"fg:{CYAN}"),
        ("instruction", f"fg:{GREY} italic"),
        ("answer", f"fg:{GOLD} bold"),
        ("disabled", f"fg:{GREY} italic"),
    ])
except ImportError:
    HAVE_QUESTIONARY = False
    _QSTYLE = None


# --- low-level ANSI fallback (also used by the worker modules) ------------
def _enable_color():
    if os.environ.get("NO_COLOR") or not sys.stdout.isatty():
        return False
    if os.name == "nt":
        try:
            k = ctypes.windll.kernel32
            h = k.GetStdHandle(-11)
            mode = ctypes.c_uint32()
            k.GetConsoleMode(h, ctypes.byref(mode))
            k.SetConsoleMode(h, mode.value | 0x0004)  # ENABLE_VIRTUAL_TERMINAL_PROCESSING
        except Exception:
            return False
    return True


_COLOR = _enable_color()


def _c(text, code):
    return f"\033[{code}m{text}\033[0m" if _COLOR else text


def bold(t):    return _c(t, "1")
def dim(t):     return _c(t, "2")
def cyan(t):    return _c(t, "96")
def green(t):   return _c(t, "92")
def yellow(t):  return _c(t, "93")
def red(t):     return _c(t, "91")
def magenta(t): return _c(t, "95")
def gold(t):    return _c(t, "33")


def glyph(unicode_char, ascii_fallback):
    enc = getattr(sys.stdout, "encoding", None) or "ascii"
    try:
        unicode_char.encode(enc)
        return unicode_char
    except (UnicodeEncodeError, LookupError):
        return ascii_fallback


DOT = glyph("●", "*")
POINTER = glyph("▶", ">")
CHECK = glyph("✓", "[ok]")
CROSS = glyph("✗", "[x]")


def ask(prompt):
    """Plain input(); exits cleanly on EOF rather than spinning a caller's loop."""
    try:
        return input(prompt).strip()
    except EOFError:
        print()
        sys.exit(0)


# --- high-level UI --------------------------------------------------------
def interactive():
    return HAVE_QUESTIONARY and sys.stdin.isatty() and sys.stdout.isatty()


def banner():
    if HAVE_RICH:
        body = Text("retro console toolkit", style=GREY)
        _console.print(Panel(
            body,
            title=f"[bold {GOLD}]ANALOGUE 3D[/] [bold {TEXT}]- UTILITY[/]",
            title_align="left", border_style=GOLD, box=box.ROUNDED, padding=(1, 2),
        ))
    else:
        title = "  ANALOGUE 3D UTILITY  "
        bar = "+" + "-" * len(title) + "+"
        print()
        print(gold(bar))
        print(gold("|") + bold(gold(title)) + gold("|"))
        print(gold(bar))


def rule(title=""):
    if HAVE_RICH:
        _console.rule(f"[{GREY}]{title}[/]" if title else "", style=GREY)
    else:
        print(dim((" " + title + " ").center(60, "-") if title else "-" * 60))


def info(msg):  _print(msg, None, TEXT)
def ok(msg):    _print(f"{CHECK} {msg}", green, GOLD)
def warn(msg):  _print(msg, yellow, "yellow")
def err(msg):   _print(f"{CROSS} {msg}", red, ERRC)


def _print(msg, ansi_fn, rich_style):
    if HAVE_RICH:
        _console.print(msg, style=rich_style, highlight=False)
    elif ansi_fn:
        print(ansi_fn(msg))
    else:
        print(msg)


def select(message, options, default=None):
    """Arrow-key menu. `options` is a list of (label, value); None = separator.
    Returns the chosen value, or None if cancelled."""
    if interactive():
        choices = [Separator() if o is None else Choice(title=o[0], value=o[1])
                   for o in options]
        try:
            return questionary.select(
                message, choices=choices, style=_QSTYLE, pointer=POINTER,
                qmark="?", instruction="(use arrow keys)", default=default,
            ).ask()
        except (KeyboardInterrupt, EOFError):
            return None

    items = [o for o in options if o is not None]
    print("\n" + bold(message))
    for i, (label, _val) in enumerate(items, 1):
        print(f"  {cyan(str(i))})  {label}")
    raw = ask("Choose (number, q to cancel): ").lower()
    if raw in ("", "q", "quit"):
        return None
    try:
        return items[int(raw) - 1][1]
    except (ValueError, IndexError):
        print(yellow("Invalid choice."))
        return None


def confirm(message, default=True):
    if interactive():
        try:
            return bool(questionary.confirm(message, default=default,
                                            style=_QSTYLE, qmark="?").ask())
        except (KeyboardInterrupt, EOFError):
            return False
    hint = "Y/n" if default else "y/N"
    r = ask(f"{message} [{hint}]: ").lower()
    if r == "":
        return default
    return r in ("y", "yes")


def text(message):
    if interactive():
        try:
            return (questionary.text(message, style=_QSTYLE, qmark="?").ask() or "").strip()
        except (KeyboardInterrupt, EOFError):
            return ""
    return ask(message + " ")

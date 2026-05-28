"""Shared terminal helpers: ANSI colors, glyphs, and input prompts."""

import os
import sys
import ctypes


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
    """Use a pretty unicode glyph only if the terminal encoding can render it."""
    enc = getattr(sys.stdout, "encoding", None) or "ascii"
    try:
        unicode_char.encode(enc)
        return unicode_char
    except (UnicodeEncodeError, LookupError):
        return ascii_fallback


DOT = glyph("●", "*")  # filled dot for status lines


def ask(prompt):
    """input() that treats no-input/EOF as an empty (cancel-friendly) answer."""
    try:
        return input(prompt).strip()
    except EOFError:
        return ""

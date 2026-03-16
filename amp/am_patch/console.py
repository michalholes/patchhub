from __future__ import annotations

import os
import re
import sys

_ANSI_RESET = "\x1b[0m"

# Basic ANSI colors (widely supported)
_ANSI_RED = "\x1b[31m"
_ANSI_GREEN = "\x1b[32m"
_ANSI_YELLOW_BASIC = "\x1b[33m"
_ANSI_BLUE = "\x1b[34m"
_ANSI_CYAN = "\x1b[36m"
_ANSI_BRIGHT_RED = "\x1b[91m"

# ANSI 256-color yellow (palette index 11). Exact RGB is not guaranteed.
_ANSI_YELLOW_256 = "\x1b[38;5;11m"


def stdout_color_enabled(mode: str) -> bool:
    """Return True if ANSI colors should be emitted to stdout.

    mode:
      - auto: enabled only when stdout is a TTY
      - always: always enabled
      - never: disabled

    Environment:
      - NO_COLOR: when set, disables color regardless of mode.
    """

    if os.getenv("NO_COLOR") is not None:
        return False

    m = str(mode or "auto").strip().lower()
    if m == "never":
        return False
    if m == "always":
        return True
    # auto
    try:
        return bool(sys.stdout.isatty())
    except Exception:
        return False


def _wrap(ansi: str, text: str, enabled: bool) -> str:
    return f"{ansi}{text}{_ANSI_RESET}" if enabled else text


def wrap_green(text: str, enabled: bool) -> str:
    return _wrap(_ANSI_GREEN, text, enabled)


def wrap_red(text: str, enabled: bool) -> str:
    return _wrap(_ANSI_RED, text, enabled)


def wrap_yellow(text: str, enabled: bool) -> str:
    # Keep legacy meaning: yellow uses 256-color palette index 11.
    return _wrap(_ANSI_YELLOW_256, text, enabled)


def wrap_blue(text: str, enabled: bool) -> str:
    return _wrap(_ANSI_BLUE, text, enabled)


def wrap_cyan(text: str, enabled: bool) -> str:
    return _wrap(_ANSI_CYAN, text, enabled)


def wrap_warning(text: str, enabled: bool) -> str:
    return _wrap(_ANSI_YELLOW_BASIC, text, enabled)


def wrap_bright_red(text: str, enabled: bool) -> str:
    return _wrap(_ANSI_BRIGHT_RED, text, enabled)


_TOKEN_PREFIX_RE = re.compile(
    r"^(?P<prefix>(RUN|DO|STATUS|OK|FAIL|RESULT|WARNING|ERROR|PUSH|COMMIT):)"
)
_RESULT_WORD_RE = re.compile(r"^(RESULT:\s+)(?P<word>SUCCESS|FAIL|CANCELED)\b")


def colorize_console_message(message: str, enabled: bool) -> str:
    """Colorize selected leading tokens in console output.

    Rules:
    - Only the leading token prefix (e.g., 'OK:', 'FAIL:') may be colored.
    - The rest of the line remains uncolored.
    - In 'RESULT: SUCCESS|FAIL|CANCELED', only the result word is colored.
    - Lines inside the final FILES block may be colored yellow when they start
      with 'A ', 'M ', or 'D '. (This is intentionally conservative.)

    When disabled, returns the original message.
    """

    if not enabled or not message:
        return message

    out_lines: list[str] = []
    # Keep line endings stable.
    for line in message.splitlines(keepends=True):
        raw = line.rstrip("\n")
        nl = "\n" if line.endswith("\n") else ""

        # FILES block entries (A/M/D + path)
        if raw.startswith(("A ", "M ", "D ")):
            out_lines.append(wrap_yellow(raw, True) + nl)
            continue

        # RESULT line: color SUCCESS/FAIL word
        m_res = _RESULT_WORD_RE.match(raw)
        if m_res:
            lead = m_res.group(1)
            word = m_res.group("word")
            rest = raw[len(lead) + len(word) :]
            if word == "SUCCESS":
                out_lines.append(lead + wrap_green(word, True) + rest + nl)
            elif word == "FAIL":
                out_lines.append(lead + wrap_red(word, True) + rest + nl)
            else:
                out_lines.append(lead + wrap_yellow(word, True) + rest + nl)
            continue

        m = _TOKEN_PREFIX_RE.match(raw)
        if not m:
            out_lines.append(raw + nl)
            continue

        prefix = m.group("prefix")
        rest = raw[len(prefix) :]

        if prefix == "OK:":
            out_lines.append(wrap_green(prefix, True) + rest + nl)
        elif prefix == "FAIL:":
            out_lines.append(wrap_red(prefix, True) + rest + nl)
        elif prefix == "WARNING:":
            out_lines.append(wrap_warning(prefix, True) + rest + nl)
        elif prefix == "ERROR:":
            out_lines.append(wrap_bright_red(prefix, True) + rest + nl)
        elif prefix in ("RUN:", "DO:"):
            out_lines.append(wrap_blue(prefix, True) + rest + nl)
        elif prefix in ("STATUS:", "PUSH:", "COMMIT:", "RESULT:"):
            out_lines.append(wrap_cyan(prefix, True) + rest + nl)
        else:
            out_lines.append(raw + nl)

    return "".join(out_lines)

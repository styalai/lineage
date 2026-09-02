"""Shared command utilities (pretty printing, error handling)."""

from __future__ import annotations

import sys
from collections.abc import Callable
from pathlib import Path
from typing import NoReturn

from .. import errors

RED = "\033[31m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
BLUE = "\033[34m"
MAGENTA = "\033[35m"
CYAN = "\033[36m"
BOLD = "\033[1m"
DIM = "\033[2m"
RESET = "\033[0m"


def is_tty() -> bool:
    try:
        return sys.stdout.isatty()
    except (AttributeError, ValueError):
        return False


_ENABLED = is_tty()


def _c(code: str, text: str) -> str:
    if not _ENABLED:
        return text
    return f"{code}{text}{RESET}"


def red(s: str) -> str:
    return _c(RED, s)


def green(s: str) -> str:
    return _c(GREEN, s)


def yellow(s: str) -> str:
    return _c(YELLOW, s)


def blue(s: str) -> str:
    return _c(BLUE, s)


def cyan(s: str) -> str:
    return _c(CYAN, s)


def bold(s: str) -> str:
    return _c(BOLD, s)


def dim(s: str) -> str:
    return _c(DIM, s)


def info(msg: str) -> None:
    print(f"{cyan('lineage:')} {msg}")


def success(msg: str) -> None:
    print(f"{green('✓')} {msg}")


def warn(msg: str) -> None:
    print(f"{yellow('!')} {msg}", file=sys.stderr)


def error(msg: str) -> None:
    print(f"{red('✗')} {msg}", file=sys.stderr)


def fail(msg: str) -> NoReturn:
    error(msg)
    raise SystemExit(1)


def run_command(fn: Callable[[], int]) -> int:
    """Run ``fn`` and convert known exceptions into nice error messages + exit code."""
    try:
        return fn()
    except errors.LineageError as e:
        error(str(e))
        return 1
    except KeyboardInterrupt:
        error("interrupted")
        return 130
    except BrokenPipeError:
        # Mirror python's default behavior for piped output.
        return 0

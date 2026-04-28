"""
setup_logging.py
================
Central logging configuration for ``setup_project.py``.

Direction of the loguru bridge: **loguru → stdlib**.
The codebase uses stdlib ``logging`` in three places (``embedding_helper``,
``neo4j_search``, the Neo4j driver itself) and ``loguru`` in only one place
(``ner_agent_auto``).  It is therefore cheaper to intercept the single
loguru sink and forward records into the stdlib root logger than to flip
every stdlib logger over to a loguru sink.  After this bridge runs, every
log line in the process — loguru, stdlib, third-party (langchain, neo4j) —
flows through the stdlib root logger and lands in the configured handlers.

Public API
----------
``configure(log_path, append=False, verbose=False, quiet=False)`` — wire up
file + console handlers, install the loguru bridge, suppress LangChain
deprecation warnings, and silence pre-existing per-module ``StreamHandler``
instances that were installed at import time before this function ran.
"""

from __future__ import annotations

import logging
import sys
import warnings
from typing import Iterable

_FILE_FORMAT = "%(asctime)s [%(levelname)-7s] %(name)s: %(message)s"
_CONSOLE_FORMAT = "  %(levelname)-7s  %(name)s: %(message)s"
_DATEFMT = "%Y-%m-%d %H:%M:%S"

# Logger names whose records are valuable in the file but never useful on
# the console at default level.  Neo4j driver notifications, langchain
# deprecation chatter, and HTTP-client byte counts all match these prefixes.
_CONSOLE_NOISE_PREFIXES: tuple = (
    "neo4j",
    "langchain",
    "httpx",
    "httpcore",
    "openai",
    "urllib3",
)

# Per-module loggers that install their own ``StreamHandler`` at import
# time.  After ``configure()`` runs we strip those handlers and let the
# records propagate to root, so the root file/console handlers become the
# single point of control.
_PER_MODULE_LOGGERS_TO_RESET: tuple = (
    "embedding_helper",
    "t2c.retrieval",
    "neo4j_search",
    "gen_schema_meta",
    "gen_system_prompt",
)


class _ConsoleNoiseFilter(logging.Filter):
    """Drop console-noisy records by logger name prefix.

    Records still reach the file handler (the filter is attached to the
    StreamHandler only), so all the chatter is preserved for grepping.
    """

    def filter(self, record: logging.LogRecord) -> bool:  # noqa: D401
        name = record.name or ""
        for p in _CONSOLE_NOISE_PREFIXES:
            if name.startswith(p):
                return False
        return True


def _install_loguru_bridge() -> None:
    """Forward every loguru record into the stdlib logger of the same name.

    We remove loguru's default sink first so messages don't double-print to
    stderr.  ``message.record["name"]`` is the originating module
    (e.g. ``"ner_agent_auto"``) so the stdlib record carries the source
    module name without any extra mapping.
    """
    try:
        from loguru import logger as _loguru
    except ImportError:
        return

    _loguru.remove()

    def _to_stdlib(message) -> None:  # type: ignore[no-untyped-def]
        rec = message.record
        std = logging.getLogger(rec["name"])
        level = rec["level"].no
        # Pass exception info if the loguru record carried one, so the
        # stdlib FileHandler can format the traceback.
        exc = rec.get("exception")
        exc_info = (exc.type, exc.value, exc.traceback) if exc else None
        std.log(level, rec["message"], exc_info=exc_info)

    _loguru.add(_to_stdlib, level="DEBUG", format="{message}")


def _suppress_langchain_deprecation() -> None:
    """Best-effort filter for the noisy LangChainDeprecationWarning emitted
    when ``langchain_community.graphs.Neo4jGraph`` is imported."""
    try:
        from langchain_core._api.deprecation import LangChainDeprecationWarning
        warnings.filterwarnings("ignore", category=LangChainDeprecationWarning)
    except Exception:
        # Fallback: match the message text so we don't depend on the
        # exact LangChain version exporting that warning class.
        warnings.filterwarnings(
            "ignore",
            message=r".*Neo4jGraph.*deprecated.*",
        )


def _reset_per_module_handlers(names: Iterable[str]) -> None:
    """Remove pre-existing StreamHandlers from named loggers and force
    propagation, so root handlers become the single output path."""
    for name in names:
        lg = logging.getLogger(name)
        # Drop everything: the FileHandler we want is the root one. Any
        # existing handler here was installed before configure() ran.
        lg.handlers.clear()
        lg.propagate = True


def configure(
    log_path: str,
    *,
    append: bool = False,
    verbose: bool = False,
    quiet: bool = False,
) -> None:
    """Configure root logging plus the loguru bridge.

    Parameters
    ----------
    log_path : Destination for the full DEBUG-level log file.
    append   : Open the log file in ``"a"`` mode instead of ``"w"``.
    verbose  : Lower the console handler to INFO and disable the noise
               filter, so ALL log records (including Neo4j driver
               notifications) reach the terminal in addition to the file.
    quiet    : Raise the console handler to WARNING (default) — kept as a
               flag for symmetry; default behaviour is already quiet.
    """
    root = logging.getLogger()
    root.setLevel(logging.DEBUG)
    for h in list(root.handlers):
        root.removeHandler(h)

    # File handler — captures EVERYTHING at DEBUG.
    fh = logging.FileHandler(log_path, mode="a" if append else "w", encoding="utf-8")
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(logging.Formatter(_FILE_FORMAT, _DATEFMT))
    root.addHandler(fh)

    # Console handler — WARNING by default, INFO in verbose. Errors and
    # warnings always reach the terminal so users see real problems.
    ch = logging.StreamHandler(sys.stderr)
    ch.setLevel(logging.INFO if verbose else logging.WARNING)
    ch.setFormatter(logging.Formatter(_CONSOLE_FORMAT))
    if not verbose:
        ch.addFilter(_ConsoleNoiseFilter())
    root.addHandler(ch)

    _reset_per_module_handlers(_PER_MODULE_LOGGERS_TO_RESET)
    _suppress_langchain_deprecation()
    _install_loguru_bridge()

    # Make sure quiet doesn't suppress the configure log line itself.
    logging.getLogger("setup_project").debug(
        "Logging configured: file=%s append=%s verbose=%s quiet=%s",
        log_path, append, verbose, quiet,
    )

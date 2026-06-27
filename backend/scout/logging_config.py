"""Structured logging used on every MCP tool call and LangGraph node.

Uses structlog when available; degrades to stdlib logging otherwise so core modules
import cleanly even before optional deps are installed.
"""

from __future__ import annotations

import logging
import sys

_CONFIGURED = False


def configure_logging(level: str = "INFO", json: bool = False) -> None:
    global _CONFIGURED
    if _CONFIGURED:
        return
    _CONFIGURED = True

    # Windows consoles default to cp1252 and choke on em dashes / check marks in
    # findings. Force UTF-8 on the standard streams.
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
        except (AttributeError, ValueError):
            pass

    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        stream=sys.stderr,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    try:
        import structlog
    except ImportError:
        return

    processors = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
    ]
    processors.append(
        structlog.processors.JSONRenderer()
        if json
        else structlog.dev.ConsoleRenderer()
    )
    structlog.configure(
        processors=processors,
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(logging, level.upper(), logging.INFO)
        ),
        logger_factory=structlog.PrintLoggerFactory(file=sys.stderr),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str):
    """Return a structlog logger if available, else a stdlib logger."""
    try:
        import structlog

        return structlog.get_logger(name)
    except ImportError:
        return logging.getLogger(name)

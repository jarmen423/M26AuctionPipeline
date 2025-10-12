"""Logging helpers using structlog."""

from __future__ import annotations

import logging
import sys

import structlog


def get_logger(name: str | None = None) -> structlog.typing.FilteringBoundLogger:
    """Return a configured structlog logger, configuring the stack on first use."""

    if not structlog.is_configured():
        configure_logging()

    return structlog.get_logger(name)


def configure_logging(level: str = "INFO") -> None:
    """Configure structlog and stdlib logging."""

    timestamper = structlog.processors.TimeStamper(fmt="iso")

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            timestamper,
            structlog.processors.add_log_level,
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(getattr(logging, level.upper(), logging.INFO)),
        logger_factory=structlog.PrintLoggerFactory(sys.stdout),
        cache_logger_on_first_use=True,
    )

    logging.basicConfig(level=level, format="%(message)s", stream=sys.stdout)

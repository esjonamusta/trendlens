from __future__ import annotations

import logging

from rich.console import Console
from rich.logging import RichHandler

console = Console()

_handler = RichHandler(
    console=console,
    rich_tracebacks=True,
    tracebacks_show_locals=False,
    show_time=True,
    show_path=False,
)


def get_logger(name: str) -> logging.Logger:
    logger = logging.getLogger(name)
    if not logger.handlers:
        logger.addHandler(_handler)
        logger.setLevel(logging.DEBUG)
        logger.propagate = False
    return logger

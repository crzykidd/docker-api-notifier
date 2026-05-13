"""
Shared logging configuration for docker-api-notifier and its notifier
modules.

Usage from any module:

    from logging_setup import get_logger
    logger = get_logger(__name__)

The first call configures handlers on the root logger. Subsequent
calls are no-ops with respect to handler setup.

Environment variables:
    NOTIFIER_LOG_TO_STDOUT  "0" disables console output. Default "1".
"""

import logging
import os
from logging.handlers import RotatingFileHandler

LOG_FILE = "/config/notifier.log"
LOG_FORMAT = "[%(asctime)s] [%(levelname)s] %(message)s"
LOG_MAX_BYTES = 10 * 1024 * 1024
LOG_BACKUP_COUNT = 4

_configured = False


def _configure_once():
    global _configured
    if _configured:
        return
    formatter = logging.Formatter(LOG_FORMAT)
    file_handler = RotatingFileHandler(
        LOG_FILE, maxBytes=LOG_MAX_BYTES, backupCount=LOG_BACKUP_COUNT
    )
    file_handler.setFormatter(formatter)
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.addHandler(file_handler)
    if os.environ.get("NOTIFIER_LOG_TO_STDOUT", "1") == "1":
        console = logging.StreamHandler()
        console.setFormatter(formatter)
        root.addHandler(console)
    _configured = True


def get_logger(name: str) -> logging.Logger:
    """Return a configured logger for the given module name."""
    _configure_once()
    return logging.getLogger(name)

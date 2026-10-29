"""Logging configuration for IDFA."""
from __future__ import annotations

import logging
import logging.handlers
import sys
from pathlib import Path

from app.config import get_config


def setup_logging() -> None:
    """Configure application-wide logging."""
    config = get_config()

    log_dir = Path(config.app.logs_dir)
    log_dir.mkdir(parents=True, exist_ok=True)

    log_file = log_dir / "idfa.log"
    error_log_file = log_dir / "idfa_error.log"

    # Root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.DEBUG if config.app.debug else logging.INFO)

    # Clear existing handlers
    root_logger.handlers.clear()

    # Formatters
    detailed_formatter = logging.Formatter(
        fmt="%(asctime)s | %(levelname)-8s | %(name)s:%(lineno)d | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    console_formatter = logging.Formatter(
        fmt="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%H:%M:%S",
    )

    # Console handler (INFO and above)
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(console_formatter)
    root_logger.addHandler(console_handler)

    # File handler (DEBUG and above, rotating)
    file_handler = logging.handlers.RotatingFileHandler(
        log_file,
        maxBytes=10 * 1024 * 1024,  # 10 MB
        backupCount=5,
        encoding="utf-8",
    )
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(detailed_formatter)
    root_logger.addHandler(file_handler)

    # Error file handler (ERROR and above)
    error_handler = logging.handlers.RotatingFileHandler(
        error_log_file,
        maxBytes=5 * 1024 * 1024,  # 5 MB
        backupCount=3,
        encoding="utf-8",
    )
    error_handler.setLevel(logging.ERROR)
    error_handler.setFormatter(detailed_formatter)
    root_logger.addHandler(error_handler)

    # Reduce noise from third-party loggers
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)

    # Log startup
    logger = logging.getLogger(__name__)
    logger.info("Logging initialized", extra={"log_file": str(log_file)})


def get_logger(name: str) -> logging.Logger:
    """Get a logger instance."""
    return logging.getLogger(name)
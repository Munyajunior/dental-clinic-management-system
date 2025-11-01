# src/utils/logger.py
import logging
import sys
from typing import Optional


def setup_logger(
    name: str,
    level: int = logging.INFO,
    format_string: Optional[str] = None,
    datefmt: Optional[str] = None,
) -> logging.Logger:
    """
    Set up a logger with consistent configuration.

    Args:
        name: Logger name (usually __name__)
        level: Logging level (default: INFO)
        format_string: Custom format string for log messages
        datefmt: Custom date format string

    Returns:
        Configured logger instance
    """
    logger = logging.getLogger(name)

    # Avoid adding handlers multiple times
    if logger.handlers:
        return logger

    # Set log level
    logger.setLevel(level)

    # Create formatter
    if format_string is None:
        format_string = "[%(asctime)s] [%(levelname)s] [%(name)s]: %(message)s"

    if datefmt is None:
        datefmt = "%Y-%m-%d %H:%M:%S"

    formatter = logging.Formatter(format_string, datefmt=datefmt)

    # Create console handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(level)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    # Prevent propagation to root logger to avoid duplicate messages
    logger.propagate = False

    return logger

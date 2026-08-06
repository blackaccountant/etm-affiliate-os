"""
Application logger.

Use this module everywhere in the project.

Example:
    from app.logging.logger import get_logger

    logger = get_logger(__name__)

    logger.info("Application started.")
"""

import logging


def get_logger(name: str) -> logging.Logger:
    """
    Return a configured logger instance.
    """
    return logging.getLogger(name)
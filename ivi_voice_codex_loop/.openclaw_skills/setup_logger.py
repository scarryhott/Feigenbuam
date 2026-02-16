"""
Skill: setup_logger
This skill sets up a logger with a specific name and logging level.
"""

import logging

def setup_logger(name: str, level: int = logging.INFO) -> logging.Logger:
    """
    Set up and return a logger with the specified name and logging level.

    :param name: Name of the logger.
    :param level: Logging level.
    :return: Configured logger.
    """
    logger = logging.getLogger(name)
    logger.setLevel(level)
    return logger

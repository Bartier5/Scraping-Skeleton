# ── utils/logger.py ──────────────────────────────────────────────────────────
# Centralized logger for the entire scraper skeleton.
# Built on loguru — a modern logging library that replaces Python's
# stdlib logging with a much cleaner API and better formatting.
#
# Usage in any other module:
#   from utils.logger import log
#   log.info("Starting scrape")
#   log.error("Request failed: {}", error)

import sys                              # needed to reference stdout for console output
from loguru import logger               # loguru's global logger instance
from config.config import Config        # pull LOG_LEVEL and LOG_FILE from central config


def setup_logger() -> logger:
    # Remove loguru's default handler — we're defining our own from scratch
    # so we have full control over format and destinations
    logger.remove()

    # ── Console Handler ──────────────────────────────────────────────────────
    # Adds a handler that prints logs to the terminal (stdout)
    logger.add(
        sys.stdout,                     # write to terminal
        level=Config.LOG_LEVEL,         # minimum level to show (e.g. DEBUG shows everything)
        colorize=True,                  # colored output in terminal for easy reading
        format=(
            "<green>{time:YYYY-MM-DD HH:mm:ss}</green> | "   # timestamp in green
            "<level>{level: <8}</level> | "                   # log level, padded to 8 chars
            "<cyan>{name}</cyan>:<cyan>{line}</cyan> | "      # module name + line number
            "<level>{message}</level>"                         # the actual log message
        )
    )

    # ── File Handler ─────────────────────────────────────────────────────────
    # Adds a second handler that writes logs to a file for persistence.
    # Useful for reviewing scrape history and debugging after the fact.
    logger.add(
        Config.LOG_FILE,                # path from config e.g. logs/scraper.log
        level=Config.LOG_LEVEL,         # same level filter as console
        rotation="10 MB",              # start a new log file when this one hits 10MB
        retention="7 days",            # automatically delete log files older than 7 days
        compression="zip",             # compress old log files to save disk space
        format=(
            "{time:YYYY-MM-DD HH:mm:ss} | "   # plain timestamp (no color for files)
            "{level: <8} | "
            "{name}:{line} | "
            "{message}"
        )
    )

    return logger


# ── Module-level logger instance ─────────────────────────────────────────────
# Call setup_logger() once here so any module that does:
#   from utils.logger import log
# gets a fully configured logger immediately, no extra setup needed.
log = setup_logger()

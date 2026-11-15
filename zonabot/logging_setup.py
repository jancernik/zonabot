"""Colored console logging and a plain `bot.log` file."""
import logging
import threading
from datetime import datetime

import psutil


class ColoredFormatter(logging.Formatter):
    """Custom formatter with colors and enhanced information"""

    COLORS = {
        'DEBUG': '\033[36m',    # Cyan
        'INFO': '\033[32m',     # Green
        'WARNING': '\033[33m',  # Yellow
        'ERROR': '\033[31m',    # Red
        'CRITICAL': '\033[35m', # Magenta
        'RESET': '\033[0m',     # Reset
        'BOLD': '\033[1m',      # Bold
        'DIM': '\033[2m'        # Dim
    }

    def format(self, record):
        process = psutil.Process()
        memory_mb = process.memory_info().rss / 1024 / 1024

        thread_count = threading.active_count()

        timestamp = datetime.fromtimestamp(record.created).strftime('%H:%M:%S.%f')[:-3]

        level_color = self.COLORS.get(record.levelname, '')
        reset = self.COLORS['RESET']
        bold = self.COLORS['BOLD']
        dim = self.COLORS['DIM']

        formatted = (
            f"{dim}[{timestamp}]{reset} "
            f"{level_color}{bold}[{record.levelname:8}]{reset} "
            f"{dim}[MEM:{memory_mb:6.1f}MB T:{thread_count:2d}]{reset} "
            f"{record.getMessage()}"
        )

        if record.levelname in ['ERROR', 'CRITICAL'] and record.exc_info:
            formatted += f"\n{dim}Exception Details:{reset}\n{self.formatException(record.exc_info)}"

        return formatted


def configure_logging(log_file="bot.log"):
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(ColoredFormatter())

    file_formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - [MEM:%(process)d MB T:%(thread)d] - %(message)s'
    )
    file_handler = logging.FileHandler(log_file)
    file_handler.setFormatter(file_formatter)

    logging.basicConfig(
        level=logging.INFO,
        handlers=[file_handler, console_handler]
    )

    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.ERROR)
    logging.getLogger("seleniumbase").setLevel(logging.WARNING)
    logging.getLogger("uc").setLevel(logging.WARNING)
    logging.getLogger("selenium").setLevel(logging.WARNING)

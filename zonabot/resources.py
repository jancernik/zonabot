"""Resource usage logged at startup and every `CHECK_INTERVAL` seconds."""
import logging
import threading

import psutil

logger = logging.getLogger(__name__)

CHECK_INTERVAL = 120


def log_startup_resources():
    try:
        memory_percent = psutil.virtual_memory().percent
        disk_percent = psutil.disk_usage('/').percent
        cpu_percent = psutil.cpu_percent(interval=1)
        logger.info(f"System resources - Memory: {memory_percent:.1f}%, Disk: {disk_percent:.1f}%, CPU: {cpu_percent:.1f}%")
        if memory_percent > 80:
            logger.warning(f"High memory usage detected: {memory_percent:.1f}%")
        if disk_percent > 90:
            logger.warning(f"High disk usage detected: {disk_percent:.1f}%")
    except Exception as e:
        logger.warning(f"Could not check system resources: {e}")


def log_resources():
    try:
        memory_percent = psutil.virtual_memory().percent
        process_memory_mb = psutil.Process().memory_info().rss / 1024 / 1024
        thread_count = threading.active_count()
        logger.info(f"Resource check - System memory: {memory_percent:.1f}%, Process memory: {process_memory_mb:.1f}MB, Threads: {thread_count}")
        if thread_count > 20:
            logger.warning(f"High thread count: {thread_count}")
    except Exception as e:
        logger.warning(f"Error during resource check: {e}")

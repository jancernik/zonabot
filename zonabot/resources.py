"""Periodic resource checks. Reboots the VM above 85% system memory and kills Chrome processes
when this process exceeds 500 MB."""
import gc
import logging
import subprocess
import threading

import psutil

logger = logging.getLogger(__name__)

CHECK_INTERVAL = 120
REBOOT_AT_SYSTEM_MEMORY_PERCENT = 85
KILL_CHROME_AT_PROCESS_MB = 500


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


def check_resources(request_reboot):
    """Calls `request_reboot()` when system memory is above the reboot threshold."""
    try:
        process = psutil.Process()
        memory_percent = psutil.virtual_memory().percent
        process_memory_mb = process.memory_info().rss / 1024 / 1024
        thread_count = threading.active_count()

        logger.info(f"Resource check - System memory: {memory_percent:.1f}%, Process memory: {process_memory_mb:.1f}MB, Threads: {thread_count}")

        if memory_percent > REBOOT_AT_SYSTEM_MEMORY_PERCENT:
            logger.warning(f"High system memory usage: {memory_percent:.1f}% - initiating system reboot")
            request_reboot()
            return
        if process_memory_mb > KILL_CHROME_AT_PROCESS_MB:
            logger.warning(f"High process memory usage: {process_memory_mb:.1f}MB")
            for _ in range(5):
                gc.collect()
            for name in ("chrome", "chromium"):
                try:
                    subprocess.run(['pkill', '-f', name], capture_output=True, timeout=3)
                except Exception:
                    pass
        if thread_count > 20:
            logger.warning(f"High thread count: {thread_count}")
    except Exception as e:
        logger.warning(f"Error during resource check: {e}")


def reboot_system():
    logger.critical("Rebooting system due to high memory usage")
    subprocess.run(['systemctl', 'reboot'], timeout=10)

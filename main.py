import os
import json
import time
import signal
import logging
import random
import threading
import requests
import sys
import psutil
import gc
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor
from contextlib import redirect_stdout, redirect_stderr
from io import StringIO

from seleniumbase import SB
from dotenv import load_dotenv
from selenium.webdriver.common.by import By
import telegram

# Load environment variables
load_dotenv()
TOKEN = os.getenv("TELEGRAM_TOKEN")
DATA_FILE = "user_data.json"

# Color codes for terminal output
class ColoredFormatter(logging.Formatter):
    """Custom formatter with colors and enhanced information"""

    # Color codes
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
        # Get memory usage
        process = psutil.Process()
        memory_mb = process.memory_info().rss / 1024 / 1024

        # Get thread count
        thread_count = threading.active_count()

        # Format timestamp
        timestamp = datetime.fromtimestamp(record.created).strftime('%H:%M:%S.%f')[:-3]

        # Color the level name
        level_color = self.COLORS.get(record.levelname, '')
        reset = self.COLORS['RESET']
        bold = self.COLORS['BOLD']
        dim = self.COLORS['DIM']

        # Enhanced format with memory and thread info
        formatted = (
            f"{dim}[{timestamp}]{reset} "
            f"{level_color}{bold}[{record.levelname:8}]{reset} "
            f"{dim}[MEM:{memory_mb:6.1f}MB T:{thread_count:2d}]{reset} "
            f"{record.getMessage()}"
        )

        # Add extra info for errors
        if record.levelname in ['ERROR', 'CRITICAL'] and record.exc_info:
            formatted += f"\n{dim}Exception Details:{reset}\n{self.formatException(record.exc_info)}"

        return formatted

# Setup enhanced logging
console_handler = logging.StreamHandler()
console_handler.setFormatter(ColoredFormatter())

file_formatter = logging.Formatter(
    '%(asctime)s - %(name)s - %(levelname)s - [MEM:%(process)d MB T:%(thread)d] - %(message)s'
)
file_handler = logging.FileHandler("bot.log")
file_handler.setFormatter(file_formatter)

logging.basicConfig(
    level=logging.INFO,
    handlers=[file_handler, console_handler]
)

# Suppress noisy loggers
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("urllib3").setLevel(logging.ERROR)
logging.getLogger("seleniumbase").setLevel(logging.WARNING)
logging.getLogger("uc").setLevel(logging.WARNING)
logging.getLogger("selenium").setLevel(logging.WARNING)

logger = logging.getLogger(__name__)

# Add memory monitoring function
def log_memory_usage(operation=""):
    """Log current memory usage"""
    process = psutil.Process()
    memory_info = process.memory_info()
    memory_mb = memory_info.rss / 1024 / 1024
    memory_percent = process.memory_percent()

    logger.info(f"Memory usage {operation}: {memory_mb:.1f} MB ({memory_percent:.1f}% of system)")

# Flag to indicate the bot is shutting down
is_shutting_down = False

def send_telegram_message(chat_id, text, reply_markup=None, disable_web_page_preview=False, retry_count=3):
    """Send a message to Telegram using direct HTTP API calls with comprehensive error handling"""
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"

    payload = {
        "chat_id": chat_id,
        "text": text,
        "disable_web_page_preview": disable_web_page_preview
    }

    # Add reply_markup if provided
    if reply_markup:
        payload["reply_markup"] = reply_markup

    for attempt in range(retry_count):
        try:
            start_time = time.time()
            response = requests.post(url, json=payload, timeout=30)
            response_time = time.time() - start_time

            if response.status_code == 200:
                if response_time > 5:
                    logger.warning(f"Slow Telegram API response: {response_time:.2f}s")
                return True
            elif response.status_code == 429:  # Rate limited
                retry_after = int(response.headers.get('Retry-After', 60))
                logger.warning(f"Rate limited by Telegram API, waiting {retry_after}s")
                time.sleep(retry_after)
                continue
            else:
                logger.error(f"Telegram API error {response.status_code}: {response.text}")

        except requests.exceptions.Timeout:
            logger.error(f"Telegram API timeout on attempt {attempt + 1}/{retry_count}")
        except requests.exceptions.ConnectionError as e:
            logger.error(f"Telegram API connection error on attempt {attempt + 1}/{retry_count}: {e}")
        except requests.exceptions.RequestException as e:
            logger.error(f"Telegram API request error on attempt {attempt + 1}/{retry_count}: {e}")
        except Exception as e:
            logger.error(f"Unexpected error sending Telegram message on attempt {attempt + 1}/{retry_count}: {e}")

        if attempt < retry_count - 1:
            wait_time = 2 ** attempt  # Exponential backoff
            logger.info(f"Retrying Telegram message in {wait_time}s...")
            time.sleep(wait_time)

    logger.error(f"Failed to send Telegram message after {retry_count} attempts")
    return False

# Global executor for managing scraper threads
executor = ThreadPoolExecutor(max_workers=5)
# Store active scraper tasks by chat_id
active_scrapers = {}
# Lock for thread-safe operations on user_data
user_data_lock = threading.RLock()

def load_users():
    """Load user data from file"""
    try:
        with open(DATA_FILE, "r") as file:
            return json.load(file)
    except (FileNotFoundError, json.JSONDecodeError) as e:
        logger.error(f"Error loading user data: {e}")
        return {}

def save_users(users):
    """Save user data to file with lock protection"""
    with user_data_lock:
        try:
            with open(DATA_FILE, "w") as file:
                json.dump(users, file, indent=4)
        except Exception as e:
            logger.error(f"Error saving user data: {e}")

# Load initial user data
user_data = load_users()

def main_menu_keyboard():
    """Create the main menu keyboard"""
    return {
        "keyboard": [
            ["Cambiar link de búsqueda"],
            ["Activar/Desactivar notificaciones"],
            ["Forzar búsqueda ahora"],
            ["Mostrar información"]
        ],
        "resize_keyboard": True
    }

def clean_url(url):
    operations = ["alquiler", "venta", "alquiler-temporal"]
    
    filters_to_remove = [
        "-publicado-hace-menos-de-2-dias",
        "-publicado-hace-menos-de-1-dia",
        "-publicado-hace-menos-de-1-semana", 
        "-publicado-hace-menos-de-15-dias",
        "-publicado-hace-menos-de-1-mes",
        "-publicado-hace-menos-de-45-dias",
        "-orden-precio-ascendente",
        "-orden-precio-descendente",
        "-orden-publicado-descendente",
        "-orden-visitas-descendente",
        "-orden-variacionporcentual-descendente"
    ]
    
    for filter_param in filters_to_remove:
        url = url.replace(filter_param, "")
    
    preferred_filter = "-publicado-hace-menos-de-1-dia-orden-publicado-descendente"
    
    for operation in operations:
        if f"-{operation}-" in url or f"/{operation}-" in url:
            parts = []
            if f"-{operation}-" in url:
                parts = url.split(f"-{operation}-", 1)
                url = f"{parts[0]}-{operation}{preferred_filter}-{parts[1]}"
            elif f"/{operation}-" in url:
                parts = url.split(f"/{operation}-", 1)
                url = f"{parts[0]}/{operation}{preferred_filter}-{parts[1]}"
            break
    
    return url
  
def is_valid_zonaprop_url(url):
    """Check if URL is a valid Zonaprop URL"""
    valid_prefixes = [
        "https://www.zonaprop.com.ar/",
        "www.zonaprop.com.ar/",
        "zonaprop.com.ar/"
    ]
    
    contains_emprendimientos = "emprendimientos" in url
    return any(url.startswith(prefix) for prefix in valid_prefixes) and not contains_emprendimientos

def set_user_url(chat_id, url, original_url):
    """Set a user's search URL"""
    with user_data_lock:
        user_data[chat_id]["url"] = url
        user_data[chat_id]["original_url"] = original_url
        user_data[chat_id]["last_seen_links"] = []
        user_data[chat_id]["last_scan"] = None
        user_data[chat_id]["initialized"] = False  # Reset initialization status
        save_users(user_data)

def toggle_user_notifications(chat_id):
    """Toggle a user's notification settings"""
    with user_data_lock:
        user_data[chat_id]["notifications"] = not user_data[chat_id]["notifications"]
        if not user_data[chat_id]["notifications"]:
            user_data[chat_id]["last_seen_links"] = []
        else:
            # If turning ON notifications, we should reset the initialization
            user_data[chat_id]["initialized"] = False
        save_users(user_data)

def restart_scraper(chat_id, initialization=False):
    """Restart the scraper for a user"""
    if is_shutting_down:
        logger.info(f"Not starting scraper for {chat_id} because system is shutting down")
        return
        
    stop_scraper(chat_id)
    
    # Schedule a new scraper task
    active_scrapers[chat_id] = executor.submit(scraper_worker, chat_id, initialization)
    logger.info(f"Started new scraper for user {chat_id}")

def stop_scraper(chat_id):
    """Stop the scraper for a user"""
    if chat_id in active_scrapers:
        # Note: This doesn't actually interrupt the thread, but marks it for cleanup
        # The thread will terminate when it checks user_data["notifications"]
        logger.info(f"Marked scraper for termination for user {chat_id}")
        # Remove from active_scrapers
        active_scrapers.pop(chat_id, None)

def scraper_worker(chat_id, initialization=False):
    """Worker function for continuous scraping"""
    logger.info(f"Starting scraper worker for user {chat_id}...")
    
    # If this is an initialization run, do one scan without notifications
    if initialization:
        single_scrape_run(chat_id, False, True)  # False for no force_notify, True for summary_only
        # After initialization, go directly to sleep to avoid double scrape
        first_run = True
    else:
        first_run = False

    while not is_shutting_down:
        try:
            # Check if we should continue running
            with user_data_lock:
                if (
                    chat_id not in user_data or
                    not user_data[chat_id].get("notifications") or
                    not user_data[chat_id].get("url")
                ):
                    logger.info(f"Stopping scraper for {chat_id} (notifications disabled or URL missing)")
                    break

            # Skip the first scrape if we just did initialization
            if not first_run:
                # Run a single scrape
                single_scrape_run(chat_id)
            else:
                first_run = False
            
            # Sleep between 4-6 minutes before next check
            sleep_time = random.uniform(240, 360)
            logger.info(f"Sleeping for {sleep_time:.1f} seconds before next scrape for {chat_id}")
            
            # Sleep in smaller increments so we can check for shutdown signal
            for _ in range(int(sleep_time / 10)):
                if is_shutting_down:
                    logger.info(f"Scraper for {chat_id} received shutdown signal during sleep")
                    break
                time.sleep(10)
                
            # Sleep the remainder
            remaining_sleep = sleep_time % 10
            if remaining_sleep > 0 and not is_shutting_down:
                time.sleep(remaining_sleep)
            
        except Exception as e:
            logger.error(f"Error in scraper loop for {chat_id}: {e}", exc_info=True)
            # Sleep for 1 minute on error before retrying
            time.sleep(60)
    
    logger.info(f"Scraper for {chat_id} exiting due to shutdown signal")

def single_scrape_run(chat_id, force_notify=False, summary_only=False):
    """Perform a single scrape run and notify if new listings found

    Args:
        chat_id: The chat ID to send notifications to
        force_notify: If True, send notifications regardless of whether ads are new
        summary_only: If True, only send a summary message, not individual ads
    """
    if is_shutting_down:
        logger.info(f"Skipping scrape for {chat_id} because system is shutting down")
        return 0

    logger.info(f"Running scrape for user {chat_id}")
    log_memory_usage("before scrape")

    # Set X11 environment variables for GUI automation
    os.environ['DISPLAY'] = ':0'
    # Try to find the correct XAUTHORITY file
    if 'XAUTHORITY' not in os.environ:
        # Check for standard location first
        xauth_home = os.path.expanduser('~/.Xauthority')
        if os.path.exists(xauth_home):
            os.environ['XAUTHORITY'] = xauth_home
        else:
            # Check for Wayland/XWayland authority file
            import glob
            xauth_pattern = f"/run/user/{os.getuid()}/.mutter-Xwaylandauth.*"
            xauth_files = glob.glob(xauth_pattern)
            if xauth_files:
                os.environ['XAUTHORITY'] = xauth_files[0]
    
    try:
        # Ensure the user still exists and has notifications enabled
        with user_data_lock:
            if chat_id not in user_data:
                logger.info(f"User {chat_id} no longer exists, stopping scrape")
                return 0
                
            if not user_data[chat_id].get("url"):
                logger.info(f"User {chat_id} has no URL configured, stopping scrape")
                return 0
                
            if not force_notify and not user_data[chat_id].get("notifications"):
                logger.info(f"User {chat_id} has notifications disabled, stopping scrape")
                return 0
                
            # Get initialization status
            is_initialized = user_data[chat_id].get("initialized", False)
        
        # Use a fresh browser instance for each scrape (suppress noisy startup messages)
        logger.info(f"Creating browser instance for {chat_id}")
        log_memory_usage("before browser creation")

        startup_output = StringIO()
        with redirect_stdout(startup_output), redirect_stderr(startup_output):
            try:
                driver_context = SB(uc=True, xvfb=False)
                driver = driver_context.__enter__()
                logger.info(f"Browser created successfully for {chat_id}")
                log_memory_usage("after browser creation")
            except Exception as e:
                logger.error(f"Failed to create browser for {chat_id}: {e}")
                gc.collect()  # Force garbage collection on error
                return 0

        try:
            url = user_data[chat_id]["url"]
            logger.info(f"Scraping URL for {chat_id}: {url}")
            
            # Open URL with retry logic
            logger.info(f"Opening URL for {chat_id}")
            driver.uc_open_with_reconnect(url, 4)
            logger.info(f"URL opened successfully for {chat_id}")

            # Handle potential CAPTCHA with timeout
            logger.info(f"Checking for CAPTCHA for {chat_id}")
            try:
                import threading
                import time

                def captcha_task():
                    try:
                        driver.uc_gui_click_captcha()
                        return True
                    except Exception as e:
                        logger.warning(f"CAPTCHA handling failed for {chat_id}: {e}")
                        return False

                # Use threading with timeout instead of signal (which doesn't work in threads)
                captcha_thread = threading.Thread(target=captcha_task)
                captcha_thread.daemon = True
                captcha_thread.start()
                captcha_thread.join(timeout=30)  # 30-second timeout

                if captcha_thread.is_alive():
                    logger.warning(f"CAPTCHA handling timed out for {chat_id}, continuing anyway")
                else:
                    logger.info(f"CAPTCHA handling completed for {chat_id}")

            except Exception as e:
                logger.warning(f"CAPTCHA handling failed for {chat_id}: {e}, continuing anyway")

            driver.sleep(1)
            logger.info(f"Starting element extraction for {chat_id}")

            # Remove suggested listings to avoid confusion
            driver.execute_script("""
                const suggested = document.querySelector("div.thin-postings-container");
                suggested && suggested.parentNode && suggested.parentNode.removeChild(suggested);
            """)
            
            # Find all property listings
            logger.info(f"Looking for property listings for {chat_id}")
            elements = driver.find_elements(By.CSS_SELECTOR, "div.postingCardLayout-module__posting-card-layout")
            logger.info(f"Found {len(elements)} elements for {chat_id}")

            # Extract links
            logger.info(f"Extracting links from elements for {chat_id}")
            new_links = {
                f"https://www.zonaprop.com.ar{el.get_attribute('data-to-posting')}"
                for el in elements
                if el.get_attribute("data-to-posting")
            }

            logger.info(f"Found {len(new_links)} listings for {chat_id}")
            logger.info(f"Processing listings data for {chat_id}")
            
            # Update last scan time
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            
            with user_data_lock:
                user_data[chat_id]["last_scan"] = timestamp
                
                # Get previously seen listings
                last_seen = set(user_data[chat_id].get("last_seen_links", []))
                
                # Identify new listings
                new_ads = new_links - last_seen
                
                # If this is the first run or force_notify is True, don't send notifications
                # Changed condition from "not last_seen" to "not is_initialized"
                if not is_initialized and not force_notify:
                    logger.info(f"First run for {chat_id}, saving {len(new_links)} initial listings")
                    
                    # Send a summary message
                    if len(new_links) == 0:
                        summary_message = (
                            f"Por ahora no encontré publicaciones que se hayan subido hoy. \n"
                            f"Voy a enviarte mensajes cuando aparezcan publicaciones nuevas."
                        )
                    else:
                        summary_message = (
                            f"Encontré {len(new_links)} publicaciones que se subieron hoy. "
                            f"Voy a enviarte mensajes cuando aparezcan publicaciones nuevas."
                        )
                    send_telegram_message(
                        chat_id=chat_id,
                        text=summary_message
                    )
                    
                    # Mark as initialized and save links
                    user_data[chat_id]["initialized"] = True
                    user_data[chat_id]["last_seen_links"] = list(new_links)
                    save_users(user_data)
                    return 1  # Count the summary message
            
            # Check if we're shutting down
            if is_shutting_down:
                logger.info(f"Aborting notification process for {chat_id} due to shutdown")
                return 0
                
            # If we have new ads to notify about
            if new_ads or force_notify:
                # Notify about new listings or force notification
                notify_ads = new_ads if not force_notify else new_links
                logger.info(f"Found {len(notify_ads)} listings to potentially notify about for {chat_id}")
                
                # Send either a summary or individual notifications
                if summary_only:
                    # Send only a summary message
                    if len(new_links) == 0:
                        summary_message = (
                            f"Por ahora no encontré publicaciones que se hayan subido hoy. \n"
                            f"Voy a enviarte mensajes cuando aparezcan publicaciones nuevas."
                        )
                    else:
                        summary_message = (
                            f"Encontré {len(new_links)} publicaciones que se subieron hoy. "
                            f"Voy a enviarte mensajes cuando aparezcan publicaciones nuevas."
                        )
                    send_telegram_message(
                        chat_id=chat_id,
                        text=summary_message
                    )
                    logger.info(f"Sent summary message to {chat_id} about {len(notify_ads)} listings")
                    
                    # Update seen listings
                    with user_data_lock:
                        if not force_notify:
                            user_data[chat_id]["last_seen_links"] = list(last_seen.union(new_ads))
                            save_users(user_data)
                    
                    return 1  # Count this as 1 message sent (the summary)
                else:
                    # Send notifications for each listing
                    sent_count = 0
                    for index, ad in enumerate(notify_ads):
                        # Check if we're shutting down
                        if is_shutting_down:
                            logger.info(f"Stopping notification process for {chat_id} due to shutdown")
                            break
                            
                        # Add toggle button to the last message
                        keyboard = None
                        if index == len(notify_ads) - 1:
                            keyboard = {
                                "inline_keyboard": [
                                    [
                                        {"text": "Desactivar notificaciones", "callback_data": f"toggle_{chat_id}"}
                                    ]
                                ]
                            }
                        
                        try:
                            # Use direct HTTP API call to send message
                            success = send_telegram_message(
                                chat_id=chat_id,
                                text=ad,
                                reply_markup=keyboard,
                                disable_web_page_preview=False
                            )
                            
                            if success:
                                sent_count += 1
                            
                            # Sleep briefly between messages to avoid flood limits
                            time.sleep(0.5)
                        except Exception as e:
                            logger.error(f"Error sending message to {chat_id}: {e}")
                    
                    logger.info(f"Sent {sent_count} individual messages to {chat_id}")
                    
                    # Update seen listings
                    with user_data_lock:
                        if not force_notify:
                            user_data[chat_id]["last_seen_links"] = list(last_seen.union(new_ads))
                            save_users(user_data)
                    
                    return sent_count
            else:
                logger.info(f"No new listings for {chat_id}")
                
                # Always save scan time
                with user_data_lock:
                    save_users(user_data)

        except Exception as e:
            logger.error(f"Error during scrape for {chat_id}: {e}", exc_info=True)
        finally:
            # Comprehensive browser cleanup
            logger.info(f"Cleaning up browser for {chat_id}")
            try:
                # Close all windows and tabs
                if 'driver' in locals():
                    try:
                        # Close all windows
                        for handle in driver.window_handles:
                            driver.switch_to.window(handle)
                            driver.close()
                    except:
                        pass

                    try:
                        driver.quit()
                    except:
                        pass

                # Close driver context
                driver_context.__exit__(None, None, None)

                # Kill any remaining Chrome processes
                try:
                    import subprocess
                    # Kill Chrome processes that might be hanging around
                    subprocess.run(['pkill', '-f', 'chrome'], capture_output=True, timeout=5)
                    subprocess.run(['pkill', '-f', 'chromium'], capture_output=True, timeout=5)
                except:
                    pass

                # Force multiple garbage collections
                for _ in range(3):
                    gc.collect()

                # Small delay to allow cleanup
                time.sleep(0.5)

                log_memory_usage("after browser cleanup")
                logger.info(f"Browser cleanup completed for {chat_id}")

            except Exception as cleanup_error:
                logger.warning(f"Error during browser cleanup for {chat_id}: {cleanup_error}")
                # Force garbage collection even if cleanup fails
                for _ in range(3):
                    gc.collect()

    except Exception as e:
        logger.error(f"Error during scrape for {chat_id}: {e}", exc_info=True)
        # Force garbage collection on any error
        gc.collect()

    log_memory_usage("end of scrape")
    return 0

def handle_message(update):
    """Handle incoming messages"""
    chat_id = str(update.get("message", {}).get("chat", {}).get("id"))
    text = update.get("message", {}).get("text", "").strip()
    
    if not chat_id or not text:
        return
    
    logger.info(f"Received message from {chat_id}: {text}")
    
    # Initialize user if not exists
    with user_data_lock:
        if chat_id not in user_data:
            if text == "/start":
                user_data[chat_id] = {
                    "url": None,
                    "original_url": None,
                    "notifications": True,
                    "last_seen_links": [],
                    "last_scan": None,
                    "awaiting_url": False,
                    "initialized": False
                }
                save_users(user_data)
                
                send_telegram_message(
                    chat_id=chat_id,
                    text="Hola! Soy un bot para ayudarte a encontrar publicaciones en Zonaprop",
                    reply_markup=main_menu_keyboard()
                )
                send_telegram_message(
                    chat_id=chat_id,
                    text="Vos te armás una búsqueda con todas las opciones y filtros que quieras y me pasás el link. "
                    "Yo me encargo de chequear si hay publicaciones nuevas y te aviso si encuentro algo",
                    reply_markup=main_menu_keyboard()
                )
                send_telegram_message(
                    chat_id=chat_id,
                    text="Podés mandarme un link directamente o usar el menú para interactuar conmigo",
                    reply_markup=main_menu_keyboard()
                )
                return
            else:
                send_telegram_message(chat_id=chat_id, text="Usá /start para inicializar el bot ;)")
                return
    
    # Check if waiting for URL
    with user_data_lock:
        if user_data[chat_id].get("awaiting_url"):
            user_data[chat_id]["awaiting_url"] = False
            save_users(user_data)
            
            if is_valid_zonaprop_url(text):
                clean_search_url = clean_url(text)
                set_user_url(chat_id, clean_search_url, text)
                send_telegram_message(
                    chat_id=chat_id,
                    text=f"Listo, ahora el link de búsqueda es:\n{text}",
                    reply_markup=main_menu_keyboard(),
                    disable_web_page_preview=True
                )
                
                # Start scraper if notifications are enabled
                if user_data[chat_id]["notifications"]:
                    restart_scraper(chat_id, True)  # True to indicate initialization
            else:
                send_telegram_message(
                    chat_id=chat_id,
                    text="El link que mandaste no es válido. Fijate que sea un link de Zonaprop. "
                    "Si pensás que es un error avisale a Jan :P",
                    reply_markup=main_menu_keyboard()
                )
            return
    
    # Handle direct URL submission
    if is_valid_zonaprop_url(text):
        clean_search_url = clean_url(text)
        set_user_url(chat_id, clean_search_url, text)
        send_telegram_message(
            chat_id=chat_id,
            text=f"Listo, ahora el link de búsqueda es:\n{text}",
            reply_markup=main_menu_keyboard(),
            disable_web_page_preview=True
        )
        
        # Start scraper if notifications are enabled
        if user_data[chat_id]["notifications"]:
            restart_scraper(chat_id, True)  # True to indicate initialization
        return
    
    # Handle menu options
    if text == "Cambiar link de búsqueda":
        with user_data_lock:
            user_data[chat_id]["awaiting_url"] = True
            save_users(user_data)
        send_telegram_message(chat_id=chat_id, text="Dale, mandame el link de la búsqueda que quieras seguir")
    
    elif text == "Activar/Desactivar notificaciones":
        toggle_user_notifications(chat_id)
        state_text = "activadas" if user_data[chat_id]["notifications"] else "desactivadas"
        send_telegram_message(
            chat_id=chat_id,
            text=f"Las notificaciones ahora están {state_text}",
            reply_markup=main_menu_keyboard()
        )
        
        # Start or stop scraper based on notification setting
        if user_data[chat_id]["notifications"] and user_data[chat_id]["url"]:
            restart_scraper(chat_id, True)  # True to indicate initialization
        else:
            stop_scraper(chat_id)
    
    elif text == "Mostrar información":
        original_url = user_data[chat_id].get("original_url") or "No configurado"
        url = user_data[chat_id]["url"] or "No configurado"
        notifications = "Activadas" if user_data[chat_id]["notifications"] else "Desactivadas"
        last_scan = "Nunca" if not user_data[chat_id].get("last_scan") else (datetime.strptime(user_data[chat_id]["last_scan"], "%Y-%m-%d %H:%M:%S") - timedelta(hours=3)).strftime("%Y-%m-%d %H:%M:%S")
        
        send_telegram_message(
            chat_id=chat_id,
            text=f"- Notificaciones: {notifications}\n"
            f"- Última búsqueda: {last_scan}\n"
            f"- Link de búsqueda: {original_url}",
            reply_markup=main_menu_keyboard(),
            disable_web_page_preview=True
        )
    
    elif text == "Forzar búsqueda ahora":
        if not user_data[chat_id]["url"]:
            send_telegram_message(
                chat_id=chat_id,
                text="Primero necesito un link de búsqueda. Podés mandarme uno directamente o usar el menú",
                reply_markup=main_menu_keyboard()
            )
            return
            
        send_telegram_message(
            chat_id=chat_id,
            text="Estoy mirando las publicaciones, dame un segundo...",
            reply_markup=main_menu_keyboard()
        )
        
        # Force a single scrape run
        executor.submit(single_scrape_run, chat_id, True, True)  # Second True means force_summary_only
    
    elif text.startswith("/"):
        # Ignore other commands
        pass
    
    else:
        send_telegram_message(
            chat_id=chat_id,
            text="Mmmm, no entendí. Mejor usá el menú para interactuar conmigo",
            reply_markup=main_menu_keyboard()
        )
        send_telegram_message(
            chat_id=chat_id,
            text="Soy medio boludo igual así que si tenés algún problema avisale a Jan :)",
            reply_markup=main_menu_keyboard()
        )

def handle_callback_query(update):
    """Handle callback queries from inline buttons"""
    query_id = update.get("callback_query", {}).get("id")
    data = update.get("callback_query", {}).get("data")
    message_id = update.get("callback_query", {}).get("message", {}).get("message_id")
    chat_id = str(update.get("callback_query", {}).get("message", {}).get("chat", {}).get("id"))
    
    if not query_id or not data or not chat_id:
        return
    
    logger.info(f"Received callback query from {chat_id}: {data}")
    
    if data.startswith("toggle_"):
        target_chat_id = data.split("_")[1]
        toggle_user_notifications(target_chat_id)
        
        # Answer the callback query
        url = f"https://api.telegram.org/bot{TOKEN}/answerCallbackQuery"
        payload = {
            "callback_query_id": query_id,
            "text": "Listo, desactivé las notificaciones"
        }
        requests.post(url, json=payload)
        
        # Edit message to remove keyboard
        url = f"https://api.telegram.org/bot{TOKEN}/editMessageReplyMarkup"
        payload = {
            "chat_id": chat_id,
            "message_id": message_id,
            "reply_markup": {}
        }
        requests.post(url, json=payload)

def get_updates(offset=None, retry_count=3):
    """Get updates from Telegram API with comprehensive error handling"""
    url = f"https://api.telegram.org/bot{TOKEN}/getUpdates"
    params = {
        "timeout": 30,
        "allowed_updates": ["message", "callback_query"]
    }
    if offset:
        params["offset"] = offset

    for attempt in range(retry_count):
        try:
            start_time = time.time()
            response = requests.get(url, params=params, timeout=35)  # Slightly longer than API timeout
            response_time = time.time() - start_time

            if response.status_code == 200:
                if response_time > 32:  # Long polling should take ~30s
                    logger.warning(f"Slow getUpdates response: {response_time:.2f}s")
                return response.json()
            else:
                logger.error(f"getUpdates API error {response.status_code}: {response.text}")

        except requests.exceptions.Timeout:
            logger.warning(f"getUpdates timeout on attempt {attempt + 1}/{retry_count} (normal for long polling)")
            if attempt == retry_count - 1:
                return {"ok": False, "error": "timeout"}
        except requests.exceptions.ConnectionError as e:
            logger.error(f"getUpdates connection error on attempt {attempt + 1}/{retry_count}: {e}")
        except requests.exceptions.RequestException as e:
            logger.error(f"getUpdates request error on attempt {attempt + 1}/{retry_count}: {e}")
        except Exception as e:
            logger.error(f"Unexpected error getting updates on attempt {attempt + 1}/{retry_count}: {e}")

        if attempt < retry_count - 1:
            wait_time = min(2 ** attempt, 10)  # Max 10s wait
            logger.info(f"Retrying getUpdates in {wait_time}s...")
            time.sleep(wait_time)

    logger.error(f"Failed to get updates after {retry_count} attempts")
    return {"ok": False, "error": "max_retries_exceeded"}

def shutdown_handler(signum, frame):
    """Handle shutdown signals properly"""
    global is_shutting_down
    is_shutting_down = True
    logger.info(f"Received shutdown signal {signum}. Starting graceful shutdown...")
    
    # Save user data one final time
    save_users(user_data)
    
    # Mark all scrapers for termination
    for chat_id in list(active_scrapers.keys()):
        stop_scraper(chat_id)
    
    # Shut down the executor
    executor.shutdown(wait=False)
    logger.info("ThreadPoolExecutor shutdown initiated")
    
    # Give threads a moment to notice the shutdown signal
    time.sleep(2)
    
    # Exit with success code
    logger.info("Exiting with success code")
    sys.exit(0)

def main():
    """Main function to start the bot"""
    # Register signal handlers for graceful shutdown
    signal.signal(signal.SIGINT, shutdown_handler)   # Ctrl+C
    signal.signal(signal.SIGTERM, shutdown_handler)  # systemctl stop

    # Log initial system state
    logger.info("=" * 60)
    logger.info("Starting ZonaProp Bot")
    logger.info("=" * 60)
    log_memory_usage("startup")

    # System resource check
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

    # Start scrapers for existing users with notifications enabled
    for chat_id in user_data.keys():
        if user_data[chat_id].get("notifications") and user_data[chat_id].get("url"):
            logger.info(f"Launching scraper thread for {chat_id}")
            restart_scraper(chat_id, True)  # True for initialization

    # Start polling
    logger.info("Bot is running and ready for messages...")
    log_memory_usage("after startup")

    # Resource monitoring variables
    last_memory_check = time.time()
    memory_check_interval = 300  # Check every 5 minutes

    offset = None
    while not is_shutting_down:
        try:
            # Periodic resource monitoring
            current_time = time.time()
            if current_time - last_memory_check > memory_check_interval:
                try:
                    process = psutil.Process()
                    memory_percent = psutil.virtual_memory().percent
                    process_memory_mb = process.memory_info().rss / 1024 / 1024
                    thread_count = threading.active_count()

                    logger.info(f"Resource check - System memory: {memory_percent:.1f}%, Process memory: {process_memory_mb:.1f}MB, Threads: {thread_count}")

                    # Alert on high memory usage
                    if memory_percent > 85:
                        logger.warning(f"High system memory usage: {memory_percent:.1f}%")
                    if process_memory_mb > 500:  # Alert if process uses more than 500MB
                        logger.warning(f"High process memory usage: {process_memory_mb:.1f}MB")
                        # Force aggressive cleanup if memory is too high
                        logger.info("Forcing aggressive garbage collection due to high memory usage")
                        for _ in range(5):
                            gc.collect()

                        # Kill any stray browser processes
                        try:
                            import subprocess
                            subprocess.run(['pkill', '-f', 'chrome'], capture_output=True, timeout=3)
                            subprocess.run(['pkill', '-f', 'chromium'], capture_output=True, timeout=3)
                        except:
                            pass
                    if thread_count > 20:  # Alert if too many threads
                        logger.warning(f"High thread count: {thread_count}")

                    last_memory_check = current_time

                except Exception as e:
                    logger.warning(f"Error during resource check: {e}")

            result = get_updates(offset)

            if result["ok"]:
                updates = result.get("result", [])

                for update in updates:
                    offset = update["update_id"] + 1

                    if "message" in update and "text" in update["message"]:
                        handle_message(update)

                    elif "callback_query" in update:
                        handle_callback_query(update)

            else:
                error_msg = result.get("error", "unknown_error")
                logger.error(f"Error in getUpdates: {error_msg}")
                # Longer sleep for persistent errors
                if error_msg == "max_retries_exceeded":
                    logger.warning("Max retries exceeded, sleeping longer...")
                    time.sleep(30)
                else:
                    time.sleep(5)

        except Exception as e:
            logger.error(f"Error in main loop: {e}", exc_info=True)
            time.sleep(5)

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        logger.info("Bot stopped by KeyboardInterrupt")
        shutdown_handler(signal.SIGINT, None)
    except SystemExit:
        # This will be triggered by our shutdown handler
        pass
    except Exception as e:
        logger.error(f"Unhandled exception: {e}", exc_info=True)
        shutdown_handler(signal.SIGTERM, None)
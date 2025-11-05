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

load_dotenv()
TOKEN = os.getenv("TELEGRAM_TOKEN")
DATA_FILE = "user_data.json"

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

logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("urllib3").setLevel(logging.ERROR)
logging.getLogger("seleniumbase").setLevel(logging.WARNING)
logging.getLogger("uc").setLevel(logging.WARNING)
logging.getLogger("selenium").setLevel(logging.WARNING)

logger = logging.getLogger(__name__)

def log_memory_usage(operation=""):
    """Log current memory usage"""
    process = psutil.Process()
    memory_info = process.memory_info()
    memory_mb = memory_info.rss / 1024 / 1024
    memory_percent = process.memory_percent()

    logger.info(f"Memory usage {operation}: {memory_mb:.1f} MB ({memory_percent:.1f}% of system)")

is_shutting_down = False

def send_telegram_message(chat_id, text, reply_markup=None, disable_web_page_preview=False, retry_count=3):
    """Send a message to Telegram using direct HTTP API calls with comprehensive error handling"""
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"

    payload = {
        "chat_id": chat_id,
        "text": text,
        "disable_web_page_preview": disable_web_page_preview
    }

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
            elif response.status_code == 429:
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
            wait_time = 2 ** attempt
            logger.info(f"Retrying Telegram message in {wait_time}s...")
            time.sleep(wait_time)

    logger.error(f"Failed to send Telegram message after {retry_count} attempts")
    return False

executor = ThreadPoolExecutor(max_workers=5)
active_scrapers = {}
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
    operations = ["alquiler", "temporal", "venta", "alquiler-temporal"]
    
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
        user_data[chat_id]["initialized"] = False
        save_users(user_data)

def toggle_user_notifications(chat_id):
    """Toggle a user's notification settings"""
    with user_data_lock:
        user_data[chat_id]["notifications"] = not user_data[chat_id]["notifications"]
        if not user_data[chat_id]["notifications"]:
            user_data[chat_id]["last_seen_links"] = []
        else:
            user_data[chat_id]["initialized"] = False
        save_users(user_data)

def restart_scraper(chat_id, initialization=False):
    """Restart the scraper for a user"""
    if is_shutting_down:
        logger.info(f"Not starting scraper for {chat_id} because system is shutting down")
        return
        
    stop_scraper(chat_id)
    
    active_scrapers[chat_id] = executor.submit(scraper_worker, chat_id, initialization)
    logger.info(f"Started new scraper for user {chat_id}")

def stop_scraper(chat_id):
    """Stop the scraper for a user"""
    if chat_id in active_scrapers:
        logger.info(f"Marked scraper for termination for user {chat_id}")
        active_scrapers.pop(chat_id, None)

def scraper_worker(chat_id, initialization=False):
    """Worker function for continuous scraping"""
    logger.info(f"Starting scraper worker for user {chat_id}...")
    
    if initialization:
        single_scrape_run(chat_id, False, True)
        first_run = True
    else:
        first_run = False

    while not is_shutting_down:
        try:
            with user_data_lock:
                if (
                    chat_id not in user_data or
                    not user_data[chat_id].get("notifications") or
                    not user_data[chat_id].get("url")
                ):
                    logger.info(f"Stopping scraper for {chat_id} (notifications disabled or URL missing)")
                    break

            if not first_run:
                single_scrape_run(chat_id)
            else:
                first_run = False
            
            sleep_time = random.uniform(240, 360)
            logger.info(f"Sleeping for {sleep_time:.1f} seconds before next scrape for {chat_id}")
            
            for _ in range(int(sleep_time / 10)):
                if is_shutting_down:
                    logger.info(f"Scraper for {chat_id} received shutdown signal during sleep")
                    break
                time.sleep(10)
                
            remaining_sleep = sleep_time % 10
            if remaining_sleep > 0 and not is_shutting_down:
                time.sleep(remaining_sleep)
            
        except Exception as e:
            logger.error(f"Error in scraper loop for {chat_id}: {e}", exc_info=True)
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

    os.environ['DISPLAY'] = ':0'
    if 'XAUTHORITY' not in os.environ:
        xauth_home = os.path.expanduser('~/.Xauthority')
        if os.path.exists(xauth_home):
            os.environ['XAUTHORITY'] = xauth_home
        else:
            import glob
            xauth_pattern = f"/run/user/{os.getuid()}/.mutter-Xwaylandauth.*"
            xauth_files = glob.glob(xauth_pattern)
            if xauth_files:
                os.environ['XAUTHORITY'] = xauth_files[0]
    
    try:
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
                
            is_initialized = user_data[chat_id].get("initialized", False)
        
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
                gc.collect()
                return 0

        try:
            url = user_data[chat_id]["url"]
            logger.info(f"Scraping URL for {chat_id}: {url}")
            
            logger.info(f"Opening URL for {chat_id}")
            driver.uc_open_with_reconnect(url, 4)
            logger.info(f"URL opened successfully for {chat_id}")

            logger.info(f"Checking for CAPTCHA for {chat_id}")
            try:
                import threading
                import time

                def captcha_task():
                    try:
                        driver.uc_gui_click_captcha()
                        return True
                    except Exception as e:
                        if "Authorization required" in str(e) or "Can't connect to display" in str(e):
                            logger.debug(f"CAPTCHA GUI unavailable for {chat_id} (X11 issue): {e}")
                        else:
                            logger.warning(f"CAPTCHA handling failed for {chat_id}: {e}")
                        return False

                captcha_thread = threading.Thread(target=captcha_task)
                captcha_thread.daemon = True
                captcha_thread.start()
                captcha_thread.join(timeout=30)

                if captcha_thread.is_alive():
                    logger.warning(f"CAPTCHA handling timed out for {chat_id}, continuing anyway")
                else:
                    logger.info(f"CAPTCHA handling completed for {chat_id}")

            except Exception as e:
                if "Authorization required" in str(e) or "Can't connect to display" in str(e):
                    logger.debug(f"CAPTCHA GUI unavailable for {chat_id} (X11 issue), continuing anyway")
                else:
                    logger.warning(f"CAPTCHA handling failed for {chat_id}: {e}, continuing anyway")

            driver.sleep(1)
            logger.info(f"Starting element extraction for {chat_id}")

            driver.execute_script("""
                const suggested = document.querySelector("div.thin-postings-container");
                suggested && suggested.parentNode && suggested.parentNode.removeChild(suggested);
            """)
            
            logger.info(f"Looking for property listings for {chat_id}")
            elements = driver.find_elements(By.CSS_SELECTOR, "div.postingCardLayout-module__posting-card-layout")
            logger.info(f"Found {len(elements)} elements for {chat_id}")

            logger.info(f"Extracting links from elements for {chat_id}")
            new_links = {
                f"https://www.zonaprop.com.ar{el.get_attribute('data-to-posting')}"
                for el in elements
                if el.get_attribute("data-to-posting")
            }

            logger.info(f"Found {len(new_links)} listings for {chat_id}")
            logger.info(f"Processing listings data for {chat_id}")
            
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            
            with user_data_lock:
                user_data[chat_id]["last_scan"] = timestamp
                
                last_seen = set(user_data[chat_id].get("last_seen_links", []))
                
                new_ads = new_links - last_seen
                
                if not is_initialized and not force_notify:
                    logger.info(f"First run for {chat_id}, saving {len(new_links)} initial listings")
                    
                    if len(new_links) == 0:
                        summary_message = (
                            f"Por ahora no encontré publicaciones que se hayan subido hoy. \n"
                            f"Voy a enviarte mensajes cuando aparezcan publicaciones nuevas."
                        )
                    else:
                        if len(new_links) == 1:
                            summary_message = (
                                f"Encontré 1 publicación que se subió hoy. "
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
                    
                    user_data[chat_id]["initialized"] = True
                    user_data[chat_id]["last_seen_links"] = list(new_links)
                    save_users(user_data)
                    return 1
            
            if is_shutting_down:
                logger.info(f"Aborting notification process for {chat_id} due to shutdown")
                return 0
                
            if new_ads or force_notify:
                notify_ads = new_ads if not force_notify else new_links
                logger.info(f"Found {len(notify_ads)} listings to potentially notify about for {chat_id}")
                
                if summary_only:
                    if len(new_links) == 0:
                        summary_message = (
                            f"Por ahora no encontré publicaciones que se hayan subido hoy. \n"
                            f"Voy a enviarte mensajes cuando aparezcan publicaciones nuevas."
                        )
                    else:
                        if len(new_links) == 1:
                            summary_message = (
                                f"Encontré 1 publicación que se subió hoy. "
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
                    
                    with user_data_lock:
                        if not force_notify:
                            user_data[chat_id]["last_seen_links"] = list(last_seen.union(new_ads))
                            save_users(user_data)
                    return 1
                else:
                    sent_count = 0
                    for index, ad in enumerate(notify_ads):
                        if is_shutting_down:
                            logger.info(f"Stopping notification process for {chat_id} due to shutdown")
                            break
                            
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
                            success = send_telegram_message(
                                chat_id=chat_id,
                                text=ad,
                                reply_markup=keyboard,
                                disable_web_page_preview=False
                            )
                            
                            if success:
                                sent_count += 1
                            
                            time.sleep(0.5)
                        except Exception as e:
                            logger.error(f"Error sending message to {chat_id}: {e}")
                    
                    logger.info(f"Sent {sent_count} individual messages to {chat_id}")
                    
                    with user_data_lock:
                        if not force_notify:
                            user_data[chat_id]["last_seen_links"] = list(last_seen.union(new_ads))
                            save_users(user_data)
                    
                    return sent_count
            else:
                logger.info(f"No new listings for {chat_id}")
                
                with user_data_lock:
                    save_users(user_data)

        except Exception as e:
            logger.error(f"Error during scrape for {chat_id}: {e}", exc_info=True)
        finally:
            logger.info(f"Cleaning up browser for {chat_id}")
            try:
                if 'driver' in locals():
                    try:
                        for handle in driver.window_handles:
                            driver.switch_to.window(handle)
                            driver.close()
                    except:
                        pass

                    try:
                        driver.quit()
                    except:
                        pass

                driver_context.__exit__(None, None, None)

                try:
                    import subprocess
                    subprocess.run(['pkill', '-f', 'chrome'], capture_output=True, timeout=5)
                    subprocess.run(['pkill', '-f', 'chromium'], capture_output=True, timeout=5)
                except:
                    pass

                for _ in range(3):
                    gc.collect()

                time.sleep(0.5)

                log_memory_usage("after browser cleanup")
                logger.info(f"Browser cleanup completed for {chat_id}")

            except Exception as cleanup_error:
                logger.warning(f"Error during browser cleanup for {chat_id}: {cleanup_error}")
                for _ in range(3):
                    gc.collect()

    except Exception as e:
        logger.error(f"Error during scrape for {chat_id}: {e}", exc_info=True)
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
                
                if user_data[chat_id]["notifications"]:
                    restart_scraper(chat_id, True)
            else:
                send_telegram_message(
                    chat_id=chat_id,
                    text="El link que mandaste no es válido. Fijate que sea un link de Zonaprop. "
                    "Si pensás que es un error avisale a Jan :P",
                    reply_markup=main_menu_keyboard()
                )
            return
    
    if is_valid_zonaprop_url(text):
        clean_search_url = clean_url(text)
        set_user_url(chat_id, clean_search_url, text)
        send_telegram_message(
            chat_id=chat_id,
            text=f"Listo, ahora el link de búsqueda es:\n{text}",
            reply_markup=main_menu_keyboard(),
            disable_web_page_preview=True
        )
        
        if user_data[chat_id]["notifications"]:
            restart_scraper(chat_id, True)
        return
    
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
        
        if user_data[chat_id]["notifications"] and user_data[chat_id]["url"]:
            restart_scraper(chat_id, True)
        else:
            stop_scraper(chat_id)
    
    elif text == "Mostrar información":
        original_url = user_data[chat_id].get("original_url") or "No configurado"
        url = user_data[chat_id]["url"] or "No configurado"
        notifications = "Activadas" if user_data[chat_id]["notifications"] else "Desactivadas"
        last_scan = "Nunca" if not user_data[chat_id].get("last_scan") else user_data[chat_id]["last_scan"]
        
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
        
        executor.submit(single_scrape_run, chat_id, True, True)
    
    elif text.startswith("/"):
        pass
    
    else:
        send_telegram_message(
            chat_id=chat_id,
            text="Mmmm, no entendí. Mejor usá el menú para interactuar conmigo",
            reply_markup=main_menu_keyboard()
        )
        send_telegram_message(
            chat_id=chat_id,
            text="No soy muy inteligente igual así que si tenés algún problema avisale a Jan :)",
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
        
        url = f"https://api.telegram.org/bot{TOKEN}/answerCallbackQuery"
        payload = {
            "callback_query_id": query_id,
            "text": "Listo, desactivé las notificaciones"
        }
        requests.post(url, json=payload)
        
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
            response = requests.get(url, params=params, timeout=35)
            response_time = time.time() - start_time

            if response.status_code == 200:
                if response_time > 32:
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
            wait_time = min(2 ** attempt, 10)
            logger.info(f"Retrying getUpdates in {wait_time}s...")
            time.sleep(wait_time)

    logger.error(f"Failed to get updates after {retry_count} attempts")
    return {"ok": False, "error": "max_retries_exceeded"}

def shutdown_handler(signum, frame):
    """Handle shutdown signals properly"""
    global is_shutting_down
    is_shutting_down = True
    logger.info(f"Received shutdown signal {signum}. Starting graceful shutdown...")
    
    save_users(user_data)
    
    for chat_id in list(active_scrapers.keys()):
        stop_scraper(chat_id)
    
    executor.shutdown(wait=False)
    logger.info("ThreadPoolExecutor shutdown initiated")
    
    time.sleep(2)
    
    logger.info("Exiting with success code")
    sys.exit(0)

def main():
    """Main function to start the bot"""
    global is_shutting_down

    signal.signal(signal.SIGINT, shutdown_handler)
    signal.signal(signal.SIGTERM, shutdown_handler)

    logger.info("=" * 60)
    logger.info("Starting ZonaProp Bot")
    logger.info("=" * 60)
    log_memory_usage("startup")

    try:
        import subprocess
        result = subprocess.run(['xhost', '+si:localuser:jan'],
                              capture_output=True, text=True, timeout=5)
        if result.returncode == 0:
            logger.info("X11 authorization configured successfully")
        else:
            logger.warning(f"X11 authorization setup failed: {result.stderr}")
    except Exception as e:
        logger.warning(f"Could not configure X11 authorization: {e}")

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

    for chat_id in user_data.keys():
        if user_data[chat_id].get("notifications") and user_data[chat_id].get("url"):
            logger.info(f"Launching scraper thread for {chat_id}")
            restart_scraper(chat_id, True)

    logger.info("Bot is running and ready for messages...")
    log_memory_usage("after startup")

    last_memory_check = time.time()
    memory_check_interval = 120

    offset = None
    while not is_shutting_down:
        try:
            current_time = time.time()
            if current_time - last_memory_check > memory_check_interval:
                try:
                    process = psutil.Process()
                    memory_percent = psutil.virtual_memory().percent
                    process_memory_mb = process.memory_info().rss / 1024 / 1024
                    thread_count = threading.active_count()

                    logger.info(f"Resource check - System memory: {memory_percent:.1f}%, Process memory: {process_memory_mb:.1f}MB, Threads: {thread_count}")

                    if memory_percent > 85:
                        logger.warning(f"High system memory usage: {memory_percent:.1f}% - initiating system reboot")

                        logger.info("Triggering graceful shutdown due to high memory usage")

                        is_shutting_down = True

                        try:
                            save_users(user_data)
                            logger.info("User data saved before reboot")
                        except Exception as e:
                            logger.error(f"Error saving user data before reboot: {e}")

                        for chat_id in list(active_scrapers.keys()):
                            stop_scraper(chat_id)

                        executor.shutdown(wait=False)

                        time.sleep(2)

                        logger.critical("Rebooting system due to high memory usage")
                        try:
                            import subprocess
                            subprocess.run(['systemctl', 'reboot'], timeout=10)
                        except Exception as e:
                            logger.error(f"Failed to reboot system: {e}")
                            sys.exit(1)
                    if process_memory_mb > 500:
                        logger.warning(f"High process memory usage: {process_memory_mb:.1f}MB")
                        logger.info("Forcing aggressive garbage collection due to high memory usage")
                        for _ in range(5):
                            gc.collect()

                        try:
                            import subprocess
                            subprocess.run(['pkill', '-f', 'chrome'], capture_output=True, timeout=3)
                            subprocess.run(['pkill', '-f', 'chromium'], capture_output=True, timeout=3)
                        except:
                            pass
                    if thread_count > 20:
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
        pass
    except Exception as e:
        logger.error(f"Unhandled exception: {e}", exc_info=True)
        shutdown_handler(signal.SIGTERM, None)
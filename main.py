import time
import threading
from selenium.webdriver.common.by import By
from seleniumbase import Driver
import telebot
from telebot import types
import random
from dotenv import load_dotenv
import os

load_dotenv()
TOKEN = os.getenv("TELEGRAM_TOKEN")

bot = telebot.TeleBot(TOKEN)

user_data = {}

# Command handler for /start


@bot.message_handler(commands=['start'])
def send_welcome(message):
    chat_id = message.chat.id
    user_data[chat_id] = {
        'url': None,
        'notifications': False,
        'last_seen_links': set()
    }
    bot.send_message(
        chat_id, "Hola! Soy un bot para notificarte de nuevas publicaciones en ZonaProp", reply_markup=main_menu())
    bot.send_message(chat_id, "Usá el menú para configurarme",
                     reply_markup=main_menu())


# Create main menu markup
def main_menu():
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.row('Cambiar URL')
    markup.row('Activar/Desactivar Mensajes')
    markup.row('Mostrar Configuración')
    return markup

# Handle text messages


@bot.message_handler(func=lambda message: True)
def handle_text(message):
    chat_id = message.chat.id
    if chat_id not in user_data:
        bot.send_message(chat_id, "Usá /start para inicializar el bot")
        return

    text = message.text

    if text == 'Cambiar URL':
        msg = bot.send_message(
            chat_id, "Mandame la URL de la búsqueda en ZonaProp que querés seguir")
        bot.register_next_step_handler(msg, set_url)

    elif text == 'Activar/Desactivar Mensajes':
        current_state = user_data[chat_id]['notifications']
        user_data[chat_id]['notifications'] = not current_state
        state_text = "activados" if not current_state else "desactivados"
        bot.send_message(chat_id, f"Perfecto, ahora los mensajes están {
                         state_text}", reply_markup=main_menu())

        # Start scraping if notifications are activated
        if not current_state:  # Notifications were off, now turned on
            start_scraping(chat_id)

    elif text == 'Mostrar Configuración':
        url = user_data[chat_id]['url'] or "no configurada"
        notifications = "activados" if user_data[chat_id]['notifications'] else "desactivados"
        bot.send_message(chat_id, f"*Configuración actual*\nURL: {url}\nMensajes: {
                         notifications}", reply_markup=main_menu(), parse_mode='Markdown')

    else:
        bot.send_message(chat_id, "Opción inválida", reply_markup=main_menu())
        bot.send_message(
            chat_id, "Usá el menú para interactuar con el bot", reply_markup=main_menu())

# Set URL handler with validation


def set_url(message):
    chat_id = message.chat.id
    url = message.text.strip()

    # Valid prefixes for the URL
    valid_prefixes = [
        "https://www.zonaprop.com.ar/departamentos",
        "www.zonaprop.com.ar/departamentos",
        "zonaprop.com.ar/departamentos"
    ]

    # Validate URL
    if any(url.startswith(prefix) for prefix in valid_prefixes):
        # Append filter to the URL
        if "/departamentos" in url:
            split_url = url.split("/departamentos")
            url = split_url[0] + \
                "/departamentos/publicado-hace-menos-de-1-dia-orden-precio-ascendente" + \
                split_url[1]

        user_data[chat_id]['url'] = url
        bot.send_message(chat_id, f"Listo, la URL ahora es: {
                         url}", reply_markup=main_menu())
    else:
        bot.send_message(chat_id, "URL inválida, fijate que sea un link de ZonaProp para buscar departamentos.",
                         reply_markup=main_menu(), parse_mode='Markdown')

# Scraping function


def scrape_zonaprop(chat_id):
    print("Scraping...")
    driver = Driver(uc=True)

    while True:
        if chat_id in user_data and user_data[chat_id]['url'] and user_data[chat_id]['notifications']:
            url = user_data[chat_id]['url']
            driver.uc_open_with_reconnect(url, 4)
            driver.uc_gui_click_captcha()

            # Find all elements with the specified class
            elements = driver.find_elements(
                By.CSS_SELECTOR, "div[class^='postingCardLayout-module__posting-card-layout__']")
            new_links = set()

            for element in elements:
                try:
                    # Get the 'data-to-posting' attribute
                    data_to_posting = element.get_attribute("data-to-posting")
                    if data_to_posting:
                        full_url = f"https://www.zonaprop.com.ar{
                            data_to_posting}"
                        new_links.add(full_url)
                except Exception as e:
                    print(f"Error extracting data: {e}")

            # Determine new ads
            last_seen = user_data[chat_id]['last_seen_links']
            if len(last_seen) == 0:
                last_seen = new_links
                # new_ads = set()
                random.choice(list(new_links))
                new_ads = {random.choice(list(new_links))}
            else:
                new_ads = new_links - last_seen

            print(f"New links: {new_links}")
            print(f"Last seen: {last_seen}")

            if new_ads:
                for ad in new_ads:
                    bot.send_message(
                        chat_id, f"{ad}", disable_web_page_preview=False)
                user_data[chat_id]['last_seen_links'] = last_seen.union(
                    new_ads)

        sleep_time = random.uniform(240, 360)
        time.sleep(sleep_time)

# Start scraping in a separate thread


def start_scraping(chat_id):
    thread = threading.Thread(target=scrape_zonaprop, args=(chat_id,))
    thread.daemon = True
    thread.start()


# Polling loop
if __name__ == '__main__':
    for chat_id in user_data.keys():
        start_scraping(chat_id)
    print("Bot is running...")
    bot.infinity_polling()

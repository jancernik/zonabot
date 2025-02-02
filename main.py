import os
import json
import time
import threading
import random
import logging
import asyncio
from dotenv import load_dotenv
from selenium.webdriver.common.by import By
from seleniumbase import Driver
from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, CallbackContext

# Load environment variables
load_dotenv()
TOKEN = os.getenv("TELEGRAM_TOKEN")

DATA_FILE = "user_data.json"

# Logging setup
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Load user data from JSON
def load_users():
    try:
        with open(DATA_FILE, "r") as file:
            return json.load(file)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}

# Save user data to JSON
def save_users(users):
    with open(DATA_FILE, "w") as file:
        json.dump(users, file, indent=4)

# Initialize user data
user_data = load_users()

# Main menu buttons
def main_menu():
    return ReplyKeyboardMarkup([
        ["Cambiar URL"],
        ["Activar/Desactivar Mensajes"],
        ["Mostrar Configuración"]
    ], resize_keyboard=True)

# /start command
async def start(update: Update, context: CallbackContext):
    chat_id = str(update.effective_chat.id)

    if chat_id not in user_data:
        user_data[chat_id] = {
            "url": None,
            "notifications": False,
            "last_seen_links": []
        }
        save_users(user_data)

    await update.message.reply_text(
        "¡Hola! Soy un bot para notificarte sobre nuevas publicaciones en ZonaProp.",
        reply_markup=main_menu()
    )
    await update.message.reply_text("Usa el menú para configurarme.", reply_markup=main_menu())

# Handle menu options & detect URL input
async def handle_text(update: Update, context: CallbackContext):
    chat_id = str(update.effective_chat.id)
    text = update.message.text.strip()

    if chat_id not in user_data:
        await update.message.reply_text("Usa /start para inicializar el bot.")
        return

    # If user was asked to send a URL, process it
    if context.user_data.get("awaiting_url"):
        context.user_data["awaiting_url"] = False  # Reset flag
        await set_url(update, context)
        # Start scraping if notifications are activated
        if user_data[chat_id]["notifications"] and user_data[chat_id]["url"]:
            threading.Thread(target=scrape_zonaprop, args=(chat_id,), daemon=True).start()
        return

    if text == "Cambiar URL":
        await update.message.reply_text("Envíame la URL de la búsqueda en ZonaProp que quieres seguir.")
        context.user_data["awaiting_url"] = True  # Set flag for next message

    elif text == "Activar/Desactivar Mensajes":
        user_data[chat_id]["notifications"] = not user_data[chat_id]["notifications"]

        if not user_data[chat_id]["notifications"]:
            user_data[chat_id]["last_seen_links"] = []  # ✅ Clear last_seen_links when disabling notifications

        save_users(user_data)
        state_text = "activados" if user_data[chat_id]["notifications"] else "desactivados"
        await update.message.reply_text(f"Las notificaciones ahora están {state_text}.", reply_markup=main_menu())

        # Start scraping if notifications are activated
        if user_data[chat_id]["notifications"] and user_data[chat_id]["url"]:
            threading.Thread(target=scrape_zonaprop, args=(chat_id,), daemon=True).start()

    elif text == "Mostrar Configuración":
        url = user_data[chat_id]["url"] or "No configurada"
        notifications = "Activados" if user_data[chat_id]["notifications"] else "Desactivados"
        await update.message.reply_text(
            f"*Configuración actual:*\n\n- URL: {url}\n- Notificaciones: {notifications}",
            reply_markup=main_menu(),
            parse_mode="Markdown"
        )

    else:
        await update.message.reply_text("Opción inválida. Usa el menú para interactuar.", reply_markup=main_menu())

# Handle URL input
async def set_url(update: Update, context: CallbackContext):
    chat_id = str(update.effective_chat.id)
    url = update.message.text.strip()

    valid_prefixes = [
        "https://www.zonaprop.com.ar/departamentos",
        "www.zonaprop.com.ar/departamentos",
        "zonaprop.com.ar/departamentos"
    ]

    if any(url.startswith(prefix) for prefix in valid_prefixes):
        if "/departamentos" in url:
            url = url.replace("-publicado-hace-menos-de-2-dias", "")
            url = url.replace("-publicado-hace-menos-de-1-dia", "")
            url = url.replace("-publicado-hace-menos-de-1-semana", "")
            url = url.replace("-publicado-hace-menos-de-15-dias", "")
            url = url.replace("-publicado-hace-menos-de-1-mes", "")
            url = url.replace("-publicado-hace-menos-de-45-dias", "")
            url = url.replace("-orden-precio-ascendente", "")
            url = url.replace("-orden-precio-descendente", "")
            url = url.replace("-orden-publicado-descendente", "")
            url = url.replace("-orden-visitas-descendente", "")
            url = url.replace("-orden-variacionporcentual-descendente", "")
            split_url = url.split("/departamentos")
            url = split_url[0] + "/departamentos/publicado-hace-menos-de-1-dia-orden-precio-ascendente" + split_url[1]

        user_data[chat_id]["url"] = url
        user_data[chat_id]["last_seen_links"] = []  # ✅ Clear last_seen_links
        save_users(user_data)

        await update.message.reply_text(f"La URL ha sido configurada como:\n{url}", reply_markup=main_menu())

    else:
        await update.message.reply_text("URL inválida. Asegúrate de enviar un link de ZonaProp válido.")

# Scraping function
def scrape_zonaprop(chat_id):
    print(f"Scraping for user {chat_id}...")
    driver = Driver(uc=True)

    app = Application.builder().token(TOKEN).build()

    while chat_id in user_data and user_data[chat_id]["url"] and user_data[chat_id]["notifications"]:
        url = user_data[chat_id]["url"]
        driver.uc_open_with_reconnect(url, 4)
        driver.uc_gui_click_captcha()

        driver.execute_script("""
          const suggested = document.querySelector("div.thin-postings-container");
          suggested && suggested.parentNode && suggested.parentNode.removeChild(suggested);
        """)

        elements = driver.find_elements(By.CSS_SELECTOR, "div.postingCardLayout-module__posting-card-layout")
        new_links = {f"https://www.zonaprop.com.ar{el.get_attribute('data-to-posting')}" for el in elements if el.get_attribute("data-to-posting")}
        
        print(new_links)
        last_seen = set(user_data[chat_id]["last_seen_links"])
        new_ads = new_links - last_seen

        if not last_seen:
            # ✅ First time scraping: Save but DON'T send messages
            user_data[chat_id]["last_seen_links"] = list(new_links)
            save_users(user_data)
            print(f"First-time scraping: Saving {len(new_links)} links for {chat_id}")
        elif new_ads:
            async def send_messages():
                async with app:
                    for ad in new_ads:
                        print("Sending message...")
                        print(ad)
                        print("-------")
                        await app.bot.send_message(chat_id=chat_id, text=ad, disable_web_page_preview=False)

            # Run the async function in the event loop
            asyncio.run(send_messages())

            user_data[chat_id]["last_seen_links"] = list(last_seen.union(new_ads))
            save_users(user_data)

        time.sleep(random.uniform(240, 360))  # Sleep 4-6 minutes

# Start the bot
def main():
    app = Application.builder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    for chat_id in user_data.keys():
        if user_data[chat_id]["notifications"]:
            threading.Thread(target=scrape_zonaprop, args=(chat_id,), daemon=True).start()

    print("Bot is running...")
    app.run_polling()

if __name__ == "__main__":
    main()

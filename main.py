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
from telegram import Update, ReplyKeyboardMarkup, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import Application, CommandHandler, MessageHandler, filters, CallbackContext, CallbackQueryHandler

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
        ["Cambiar link de búsqueda"],
        ["Activar/Desactivar notificaciones"],
        ["Mostrar configuración"]
    ], resize_keyboard=True)

# /start command


async def start(update: Update, context: CallbackContext):
    chat_id = str(update.effective_chat.id)

    if chat_id not in user_data:
        user_data[chat_id] = {
            "url": None,
            "notifications": True,
            "last_seen_links": []
        }
        save_users(user_data)

    await update.message.reply_text(
        "Hola! Soy un bot para ayudarte a encontrar publicaciones en Zonaprop",
        reply_markup=main_menu()
    )
    await update.message.reply_text(
        "Vos te armás una búsqueda con todas las opciones y filtros que quieras y me pasás el link. Yo me encargo de chequear si hay publicaciones nuevas y te aviso si encuentro algo",
        reply_markup=main_menu()
    )
    await update.message.reply_text("Podés mandarme un link directamente o usar el menú para interactuar conmigo", reply_markup=main_menu())


async def handle_text(update: Update, context: CallbackContext):
    chat_id = str(update.effective_chat.id)
    text = update.message.text.strip()

    if chat_id not in user_data:
        await update.message.reply_text("Usá /start para inicializar el bot ;)")
        return

    valid_prefixes = [
        "https://www.zonaprop.com.ar/departamentos",
        "www.zonaprop.com.ar/departamentos",
        "zonaprop.com.ar/departamentos"
    ]

    # ✅ If user previously selected "Cambiar link de búsqueda", validate their input
    if context.user_data.get("awaiting_url"):
        context.user_data["awaiting_url"] = False  # Reset flag

        if any(text.startswith(prefix) for prefix in valid_prefixes):
            user_data[chat_id]["url"] = text
            # ✅ Clear last_seen_links when setting a new URL
            user_data[chat_id]["last_seen_links"] = []
            save_users(user_data)

            await update.message.reply_text(f"Listo, ahora el link de búsqueda es:\n{text}", reply_markup=main_menu(), disable_web_page_preview=True)

            if user_data[chat_id]["notifications"]:
                threading.Thread(target=scrape_zonaprop, args=(
                    chat_id,), daemon=True).start()
        else:
            await update.message.reply_text("El link que mandaste no es válido. Fijate que sea un link de Zonaprop. Si pensás que es un error avisale a Jan :P", reply_markup=main_menu())

        return  # ✅ Exit function after handling URL

    # ✅ If user sends a valid ZonaProp URL directly, process it
    if any(text.startswith(prefix) for prefix in valid_prefixes):
        user_data[chat_id]["url"] = text
        # ✅ Clear last_seen_links when setting a new URL
        user_data[chat_id]["last_seen_links"] = []
        save_users(user_data)

        await update.message.reply_text(f"Listo, ahora el link de búsqueda es:\n{text}", reply_markup=main_menu(), disable_web_page_preview=True)

        if user_data[chat_id]["notifications"]:
            threading.Thread(target=scrape_zonaprop, args=(
                chat_id,), daemon=True).start()
        return  # ✅ Exit function after handling URL

    # ✅ Handle existing menu options
    if text == "Cambiar link de búsqueda":
        await update.message.reply_text("Dale, mandame el link de la búsqueda que quieras seguir")
        # Set flag to expect a URL input
        context.user_data["awaiting_url"] = True

    elif text == "Activar/Desactivar notificaciones":
        user_data[chat_id]["notifications"] = not user_data[chat_id]["notifications"]

        if not user_data[chat_id]["notifications"]:
            user_data[chat_id]["last_seen_links"] = []

        save_users(user_data)
        state_text = "activadas" if user_data[chat_id]["notifications"] else "desactivadas"
        await update.message.reply_text(f"Las notificaciones ahora están {state_text}", reply_markup=main_menu())

        if user_data[chat_id]["notifications"] and user_data[chat_id]["url"]:
            threading.Thread(target=scrape_zonaprop, args=(
                chat_id,), daemon=True).start()

    elif text == "Mostrar configuración":
        url = user_data[chat_id]["url"] or "No configurado"
        notifications = "Activadas" if user_data[chat_id]["notifications"] else "Desactivadas"
        await update.message.reply_text(
            f"*Configuración actual:*\n\n- Notificaciones: {
                notifications}\n- Link de búsqueda: {url}",
            reply_markup=main_menu(),
            parse_mode="Markdown",
            disable_web_page_preview=True
        )

    else:
        # ✅ If input is neither a valid URL nor a menu option, send generic error
        await update.message.reply_text("Mmmm, no entendí. Mejor usá el menú para interactuar conmigo", reply_markup=main_menu())
        await update.message.reply_text("Soy medio boludo igual así que si tenés algún problema avisale a Jan :)", reply_markup=main_menu())

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
        user_data[chat_id]["url"] = url
        user_data[chat_id]["last_seen_links"] = []
        save_users(user_data)

        await update.message.reply_text(f"Listo, ahora el link de búsqueda es:\n{url}", reply_markup=main_menu())

    else:
        await update.message.reply_text("El link que mandaste no es válido. Fijate que sea un link de Zonaprop. Si pensás que es un error avisale a Jan :P")

# Scraping function


def scrape_zonaprop(chat_id):
    print(f"Scraping for user {chat_id}...")
    driver = Driver(uc=True)
    app = Application.builder().token(TOKEN).build()

    while True:
        if chat_id not in user_data or not user_data[chat_id]["notifications"] or not user_data[chat_id]["url"]:
            print(f"Stopping scraper for {
                  chat_id} (notifications disabled or URL missing)")
            break

        url = user_data[chat_id]["url"]
        driver.uc_open_with_reconnect(url, 4)
        driver.uc_gui_click_captcha()

        driver.execute_script("""
          const suggested = document.querySelector("div.thin-postings-container");
          suggested && suggested.parentNode && suggested.parentNode.removeChild(suggested);
        """)

        elements = driver.find_elements(
            By.CSS_SELECTOR, "div.postingCardLayout-module__posting-card-layout")
        new_links = {f"https://www.zonaprop.com.ar{el.get_attribute(
            'data-to-posting')}" for el in elements if el.get_attribute("data-to-posting")}

        print(f"New links found for {chat_id}: {new_links}")
        last_seen = set(user_data[chat_id]["last_seen_links"])
        new_ads = new_links - last_seen

        if not last_seen:
            user_data[chat_id]["last_seen_links"] = list(new_links)
            save_users(user_data)
        elif new_ads:
            async def send_messages():
                async with app:
                    for index, ad in enumerate(new_ads):
                        if index == len(new_ads) - 1:
                            keyboard = InlineKeyboardMarkup([
                                [InlineKeyboardButton(
                                    "Desactivar notificaciones", callback_data=f"toggle_{chat_id}")]
                            ])
                            await app.bot.send_message(
                                chat_id=chat_id,
                                text=ad,
                                disable_web_page_preview=False,
                                reply_markup=keyboard
                            )
                        else:
                            await app.bot.send_message(chat_id=chat_id, text=ad, disable_web_page_preview=False)

            asyncio.run(send_messages())

            user_data[chat_id]["last_seen_links"] = list(
                last_seen.union(new_ads))
            save_users(user_data)

        time.sleep(random.uniform(240, 360))

# Handle inline button click


async def toggle_notifications(update: Update, context: CallbackContext):
    query = update.callback_query
    chat_id = str(query.message.chat_id)

    user_data[chat_id]["notifications"] = False
    user_data[chat_id]["last_seen_links"] = []
    save_users(user_data)

    await query.edit_message_reply_markup(reply_markup=None)
    await query.answer("Listo, desactivé las notificaciones")

# Start the bot


def main():
    app = Application.builder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(
        filters.TEXT & ~filters.COMMAND, handle_text))
    app.add_handler(CallbackQueryHandler(
        toggle_notifications, pattern=r"toggle_\d+"))

    for chat_id in user_data.keys():
        if user_data[chat_id]["notifications"]:
            print(f"Starting scraper for {chat_id}")
            threading.Thread(target=scrape_zonaprop, args=(
                chat_id,), daemon=True).start()

    print("Bot is running...")
    app.run_polling()


if __name__ == "__main__":
    main()

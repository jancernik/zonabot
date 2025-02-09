import os
import json
import time
import threading
import random
import logging
import asyncio
from seleniumbase import SB
from dotenv import load_dotenv
from selenium.webdriver.common.by import By
from seleniumbase import Driver
from telegram import Update, ReplyKeyboardMarkup, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import Application, CommandHandler, MessageHandler, filters, CallbackContext, CallbackQueryHandler

load_dotenv()
TOKEN = os.getenv("TELEGRAM_TOKEN")

DATA_FILE = "user_data.json"

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def load_users():
    try:
        with open(DATA_FILE, "r") as file:
            return json.load(file)
    except (FileNotFoundError, json.JSONDecodeError) as e:
        logger.error(f"Error loading user data: {e}")
        return {}

def save_users(users):
    try:
        with open(DATA_FILE, "w") as file:
            json.dump(users, file, indent=4)
    except Exception as e:
        logger.error(f"Error saving user data: {e}")

user_data = load_users()

def main_menu():
    return ReplyKeyboardMarkup([
        ["Cambiar link de búsqueda"],
        ["Activar/Desactivar notificaciones"],
        ["Mostrar configuración"]
    ], resize_keyboard=True)

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
    
def clean_url(url):
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
  return url

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

    if context.user_data.get("awaiting_url"):
        context.user_data["awaiting_url"] = False

        if any(text.startswith(prefix) for prefix in valid_prefixes):
            text = clean_url(text)
            user_data[chat_id]["url"] = text
            user_data[chat_id]["last_seen_links"] = []
            save_users(user_data)

            await update.message.reply_text(f"Listo, ahora el link de búsqueda es:\n{text}", reply_markup=main_menu(), disable_web_page_preview=True)

            if user_data[chat_id]["notifications"]:
                threading.Thread(target=scrape_zonaprop, args=(
                    chat_id,), daemon=True).start()
        else:
            await update.message.reply_text("El link que mandaste no es válido. Fijate que sea un link de Zonaprop. Si pensás que es un error avisale a Jan :P", reply_markup=main_menu())
        return

    if any(text.startswith(prefix) for prefix in valid_prefixes):
        text = clean_url(text)
        user_data[chat_id]["url"] = text
        user_data[chat_id]["last_seen_links"] = []
        save_users(user_data)

        await update.message.reply_text(f"Listo, ahora el link de búsqueda es:\n{text}", reply_markup=main_menu(), disable_web_page_preview=True)

        if user_data[chat_id]["notifications"]:
            threading.Thread(target=scrape_zonaprop, args=(
                chat_id,), daemon=True).start()
        return

    if text == "Cambiar link de búsqueda":
        await update.message.reply_text("Dale, mandame el link de la búsqueda que quieras seguir")
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
            f"*Configuración actual:*\n\n- Notificaciones: {notifications}\n- Link de búsqueda: {url}",
            reply_markup=main_menu(),
            parse_mode="Markdown",
            disable_web_page_preview=True
        )

    else:
        await update.message.reply_text("Mmmm, no entendí. Mejor usá el menú para interactuar conmigo", reply_markup=main_menu())
        await update.message.reply_text("Soy medio boludo igual así que si tenés algún problema avisale a Jan :)", reply_markup=main_menu())

async def set_url(update: Update, context: CallbackContext):
    chat_id = str(update.effective_chat.id)
    url = update.message.text.strip()

    valid_prefixes = [
        "https://www.zonaprop.com.ar/departamentos",
        "www.zonaprop.com.ar/departamentos",
        "zonaprop.com.ar/departamentos"
    ]

    if any(url.startswith(prefix) for prefix in valid_prefixes):
        url = clean_url(url)
        user_data[chat_id]["url"] = url
        user_data[chat_id]["last_seen_links"] = []
        save_users(user_data)

        await update.message.reply_text(f"Listo, ahora el link de búsqueda es:\n{url}", reply_markup=main_menu())

    else:
        await update.message.reply_text("El link que mandaste no es válido. Fijate que sea un link de Zonaprop. Si pensás que es un error avisale a Jan :P")

def scrape_zonaprop(chat_id):
    logger.info(f"Starting scraper for user {chat_id}...")
    app = Application.builder().token(TOKEN).build()

    while True:
        try:
            if chat_id not in user_data or not user_data[chat_id].get("notifications") or not user_data[chat_id].get("url"):
                logger.info(f"Stopping scraper for {chat_id} (notifications disabled or URL missing)")
                break

            with SB(uc=True, xvfb=True) as driver:
                url = user_data[chat_id]["url"]
                logger.info(f"Scraping URL for {chat_id}: {url}")
                driver.uc_open_with_reconnect(url, 4)
                driver.uc_gui_click_captcha()
                driver.sleep(1)

                driver.execute_script("""
                  const suggested = document.querySelector("div.thin-postings-container");
                  suggested && suggested.parentNode && suggested.parentNode.removeChild(suggested);
                """)

                elements = driver.find_elements(By.CSS_SELECTOR, "div.postingCardLayout-module__posting-card-layout")
                new_links = {f"https://www.zonaprop.com.ar{el.get_attribute('data-to-posting')}" for el in elements if el.get_attribute("data-to-posting")}
                logger.info(f"Found {len(new_links)} new links for {chat_id}")

                last_seen = set(user_data[chat_id]["last_seen_links"])
                new_ads = new_links - last_seen

                if not last_seen:
                    user_data[chat_id]["last_seen_links"] = list(new_links)
                    save_users(user_data)
                elif new_ads:
                    async def send_messages():
                        async with app:
                            for index, ad in enumerate(new_ads):
                                keyboard = None
                                if index == len(new_ads) - 1:
                                    keyboard = InlineKeyboardMarkup([
                                        [InlineKeyboardButton("Desactivar notificaciones", callback_data=f"toggle_{chat_id}")]
                                    ])
                                await app.bot.send_message(chat_id=chat_id, text=ad, disable_web_page_preview=False, reply_markup=keyboard)
                    
                    asyncio.run(send_messages())
                    user_data[chat_id]["last_seen_links"] = list(last_seen.union(new_ads))
                    save_users(user_data)

                sleep_time = random.uniform(4, 7)
                # sleep_time = random.uniform(240, 360)
                logger.info(f"Sleeping for {sleep_time} seconds before next scrape for {chat_id}")
                time.sleep(sleep_time)

        except Exception as e:
            logger.error(f"Error in scraper loop for {chat_id}: {e}")
            # time.sleep(60)  # Wait before retrying to prevent a crash loop
            time.sleep(6) 

async def toggle_notifications(update: Update, context: CallbackContext):
    query = update.callback_query
    chat_id = str(query.message.chat_id)

    user_data[chat_id]["notifications"] = False
    user_data[chat_id]["last_seen_links"] = []
    save_users(user_data)

    await query.edit_message_reply_markup(reply_markup=None)
    await query.answer("Listo, desactivé las notificaciones")

def main():
    app = Application.builder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    app.add_handler(CallbackQueryHandler(toggle_notifications, pattern=r"toggle_\d+"))

    for chat_id in user_data.keys():
        if user_data[chat_id].get("notifications"):
            logger.info(f"Launching scraper thread for {chat_id}")
            threading.Thread(target=scrape_zonaprop, args=(chat_id,), daemon=True).start()

    logger.info("Bot is running...")
    app.run_polling()

if __name__ == "__main__":
    main()

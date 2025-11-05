# ZonaBot

Very rudimentary Telegram bot that scrapes [Zonaprop](https://www.zonaprop.com.ar) and notifies users when new property listings are published.

Message on Telegram: [@ZonaBot](https://t.me/JanZonapropBot)

## How it works
- You send the bot a Zonaprop search link (with your filters applied).
- It checks the site every few minutes for new listings.
- When new results appear, it sends you a message on Telegram.

## Requirements

- A working Chrome/Chromium install.
- A VM with a functional display (X11) or a real machine. Fully headless environments won't work.

## Running locally

Create and activate a virtual environment:

```bash
python3 -m venv venv
source venv/bin/activate
```

Install dependencies:

```bash
pip install -r requirements.txt
```

Set your Telegram bot token (from BotFather):

```bash
export TELEGRAM_TOKEN="your_token_here"
```

Run the bot:

```bash
python main.py
```

---

>[!NOTE]
> - This is a hobby project, meant as a tool for for friends and family, not a complete public service.
> - It is currently self-hosted and not designed to be a bulletproof system.
> - There is no guarantee it won’t break or go down.

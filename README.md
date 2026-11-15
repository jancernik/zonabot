# ZonaBot

Very rudimentary Telegram bot that scrapes [Zonaprop](https://www.zonaprop.com.ar) and notifies users when new property listings are published.

Message on Telegram: [@ZonaBot](https://t.me/JanZonapropBot)

## How it works
- You send the bot a Zonaprop search link (with your filters applied).
- It replies with how many listings the search has today, then checks the site every few minutes.
- When new listings appear, it sends you each one on Telegram (at most 10 at once, then a link to the rest).

## Requirements

- A working Chrome/Chromium install.
- A VM with a functional display (X11) or a real machine. Fully headless environments won't work.

## Configuration

Environment variables (a `.env` file next to `main.py` is loaded automatically):

| Variable | Required | Meaning |
|---|---|---|
| `TELEGRAM_TOKEN` | yes | Bot token from BotFather |
| `ADMIN_CHAT_ID` | no | Chat that gets a message after 6 failed checks in a row, and when checks recover |
| `ZONABOT_DATA_FILE` | no | Data file path, default `user_data.json` |

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

A systemd unit for running it as a service is in `deploy/zonaprop-bot.service`.

## Tests

```bash
pip install -r requirements-dev.txt
python -m pytest
```

---

>[!NOTE]
> - This is a hobby project, meant as a tool for friends and family, not a complete public service.
> - It is currently self-hosted and not designed to be a bulletproof system.
> - There is no guarantee it won’t break or go down.

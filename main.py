import re
import requests
import os
import asyncio
from datetime import datetime, timedelta
from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

TOKEN = os.environ["BOT_TOKEN"]
URL = "https://api.loe.lviv.ua/api/menus?page=1&type=photo-grafic"

USERS_TO_NOTIFY = set()


# ---------- ВСПОМОГАТЕЛЬНЫЕ ----------

def normalize_api_data(data):
    """
    API иногда возвращает dict, иногда list
    → приводим всё к списку hydra:member
    """
    if isinstance(data, dict):
        return data.get("hydra:member", [])
    if isinstance(data, list):
        return data
    return []


def parse_time_interval(text):
    text = text.strip()
    text = re.sub(r"^з\s*", "", text)

    start_str, end_str = text.split(" до ")

    if start_str == "24:00":
        start_str = "00:00"
    if end_str == "24:00":
        end_str = "00:00"

    start = datetime.strptime(start_str, "%H:%M").time()
    end = datetime.strptime(end_str, "%H:%M").time()
    return start, end


# ---------- ОСНОВНАЯ ЛОГИКА ----------

def extract_latest_html_by_date(members):
    """
    Возвращает dict:
    {
      "dd.mm.yyyy": rawHtml (самый свежий по времени)
    }
    """
    result = {}

    for member in members:
        menu_items = member.get("menuItems", [])
        for item in menu_items:
            raw = item.get("rawHtml", "")
            date_match = re.search(
                r"Графік погодинних відключень на (\d{2}\.\d{2}\.\d{4})",
                raw,
            )
            if not date_match:
                continue

            date_str = date_match.group(1)

            time_match = re.search(
                r"Інформація станом на (\d{2}:\d{2})",
                raw,
            )
            info_time = time_match.group(1) if time_match else "00:00"

            if (
                date_str not in result
                or info_time > result[date_str]["time"]
            ):
                result[date_str] = {
                    "time": info_time,
                    "raw": raw,
                }

    return {k: v["raw"] for k, v in result.items()}


def format_group_52(raw_html, date_str, today):
    match = re.search(
        r"Група 5\.2\..*?немає з (.+?)\.",
        raw_html,
    )

    if not match:
        return f"📅 *{date_str}*\n\nДанных нет"

    intervals = [i.strip() for i in match.group(1).split(",")]
    now = datetime.now().time()
    lines = []

    for interval in intervals:
        start, end = parse_time_interval(interval)

        if date_str == today:
            if end <= now:
                continue

        lines.append(f"{start.strftime('%H:%M')} - {end.strftime('%H:%M')}")

    if not lines:
        return f"📅 *{date_str}*\n\nОтключений больше нет"

    return f"📅 *{date_str}*\n\n" + "\n".join(lines)


def get_group_52():
    r = requests.get(URL, headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
    r.raise_for_status()

    raw_data = r.json()
    members = normalize_api_data(raw_data)
    html_by_date = extract_latest_html_by_date(members)

    today = datetime.now().strftime("%d.%m.%Y")
    tomorrow = (datetime.now() + timedelta(days=1)).strftime("%d.%m.%Y")

    parts = []

    if today in html_by_date:
        parts.append(format_group_52(html_by_date[today], today, today))

    if tomorrow in html_by_date:
        parts.append(format_group_52(html_by_date[tomorrow], tomorrow, today))

    return "\n\n".join(parts) if parts else "Данных нет"


# ---------- TELEGRAM ----------

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    USERS_TO_NOTIFY.add(update.effective_user.id)
    keyboard = ReplyKeyboardMarkup(
        [["Когда отключат"]],
        resize_keyboard=True,
    )
    await update.message.reply_text(
        get_group_52(),
        reply_markup=keyboard,
        parse_mode="Markdown",
    )


async def button_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text == "Когда отключат":
        await update.message.reply_text(
            get_group_52(),
            parse_mode="Markdown",
        )


async def notify_loop(app):
    sent = set()

    while True:
        try:
            r = requests.get(URL, headers={"User-Agent": "Mozilla/5.0"}, timeout=10)
            r.raise_for_status()

            members = normalize_api_data(r.json())
            html_by_date = extract_latest_html_by_date(members)

            today = datetime.now().strftime("%d.%m.%Y")
            raw = html_by_date.get(today)
            if not raw:
                await asyncio.sleep(60)
                continue

            match = re.search(
                r"Група 5\.2\..*?немає з (.+?)\.",
                raw,
            )
            if not match:
                await asyncio.sleep(60)
                continue

            now = datetime.now()
            for interval in match.group(1).split(","):
                start, end = parse_time_interval(interval)
                start_dt = datetime.combine(now.date(), start)
                notify_dt = start_dt - timedelta(hours=1)

                key = f"{start_dt}"

                if (
                    notify_dt <= now < notify_dt + timedelta(minutes=1)
                    and key not in sent
                ):
                    sent.add(key)
                    for uid in USERS_TO_NOTIFY:
                        await app.bot.send_message(
                            uid,
                            f"⏰ Через час отключение\n{start.strftime('%H:%M')} - {end.strftime('%H:%M')}",
                        )

        except:
            pass

        await asyncio.sleep(60)


# ---------- ЗАПУСК ----------

app = ApplicationBuilder().token(TOKEN).build()
app.add_handler(CommandHandler("start", start))
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, button_message))

asyncio.get_event_loop().create_task(notify_loop(app))
app.run_polling()

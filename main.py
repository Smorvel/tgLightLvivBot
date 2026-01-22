import re
import requests
import os
import asyncio
from datetime import datetime, timedelta, time
from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, ContextTypes, filters

TOKEN = os.environ["BOT_TOKEN"]  # вставь сюда токен бота
URL = "https://api.loe.lviv.ua/api/menus?page=1&type=photo-grafic"

USERS_TO_NOTIFY = set()  # сюда добавляем пользователей для уведомлений

def parse_time_interval(interval_str):
    """Парсит строку 'з 03:00 до 06:00' или '03:00 до 06:00' в кортеж datetime.time"""
    interval_str = interval_str.strip()
    if interval_str.startswith("з "):
        interval_str = interval_str[2:]
    start_str, end_str = interval_str.split(" до ")
    if start_str.strip() == "24:00":
        start_str = "23:59"
    if end_str.strip() == "24:00":
        end_str = "23:59"
    start = datetime.strptime(start_str.strip(), "%H:%M").time()
    end = datetime.strptime(end_str.strip(), "%H:%M").time()
    return start, end

def get_group_52():
    """Возвращает график группы 5.2 в красивом формате с Markdown"""
    headers = {"User-Agent": "Mozilla/5.0"}
    r = requests.get(URL, headers=headers, timeout=10)
    r.raise_for_status()
    data = r.json()
    raw_html = data["hydra:member"][0]["menuItems"][0]["rawHtml"]

    # Дата графика
    date_match = re.search(r"Графік погодинних відключень на (\d{2}\.\d{2}\.\d{4})", raw_html)
    date_str = date_match.group(1) if date_match else "неизвестно"

    # Интервалы группы 5.2
    group_match = re.search(r"Група 5\.2\..*?немає з (.+?)\.", raw_html)
    if not group_match:
        return f"📅 *{date_str}*\n\nДанных для группы 5.2 нет"

    intervals_str = group_match.group(1)
    intervals = [s.strip() for s in intervals_str.split(",")]

    now = datetime.now().time()
    future_intervals = []
    for interval in intervals:
        start, end = parse_time_interval(interval)
        if end > now:
            future_intervals.append(f"{start.strftime('%H:%M')} - {end.strftime('%H:%M')}")

    if not future_intervals:
        return f"📅 *{date_str}*\n\nСегодня отключений больше нет"

    # Формируем текст с эмодзи и пустой строкой перед временем
    result = f"📅 *{date_str}*\n\n" + "\n".join(future_intervals)
    return result

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик команды /start"""
    USERS_TO_NOTIFY.add(update.effective_user.id)
    keyboard = [["Когда отключат"]]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    await update.message.reply_text(get_group_52(), reply_markup=reply_markup, parse_mode="Markdown")

async def button_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик нажатия кнопки ReplyKeyboard"""
    if update.message.text == "Когда отключат":
        await update.message.reply_text(get_group_52(), parse_mode="Markdown")

async def notify_loop(app):
    """Цикл уведомлений за час до отключения"""
    while True:
        try:
            headers = {"User-Agent": "Mozilla/5.0"}
            r = requests.get(URL, headers=headers, timeout=10)
            r.raise_for_status()
            data = r.json()
            raw_html = data["hydra:member"][0]["menuItems"][0]["rawHtml"]
            group_match = re.search(r"Група 5\.2\..*?немає з (.+?)\.", raw_html)
            if group_match:
                intervals_str = group_match.group(1)
                intervals = [s.strip() for s in intervals_str.split(",")]
                now_dt = datetime.now()
                for interval in intervals:
                    start, end = parse_time_interval(interval)
                    start_dt = datetime.combine(now_dt.date(), start)
                    notify_time = start_dt - timedelta(hours=1)
                    if now_dt <= notify_time <= now_dt + timedelta(minutes=1):
                        message = f"Через час отключение! {start.strftime('%H:%M')} - {end.strftime('%H:%M')}"
                        for user_id in USERS_TO_NOTIFY:
                            try:
                                await app.bot.send_message(chat_id=user_id, text=message)
                            except:
                                pass
        except:
            pass
        await asyncio.sleep(60)  # проверяем каждую минуту

# Создаём приложение бота
app = ApplicationBuilder().token(TOKEN).build()
app.add_handler(CommandHandler("start", start))
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, button_message))

# Запускаем цикл уведомлений в фоне
asyncio.get_event_loop().create_task(notify_loop(app))

# Запуск бота
app.run_polling()

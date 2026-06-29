import math
import os
import datetime
import calendar
import psycopg2

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, BotCommand
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
)

TOKEN = os.getenv("BOT_TOKEN")
DATABASE_URL = os.getenv("DATABASE_URL")

conn = psycopg2.connect(DATABASE_URL)
conn.autocommit = True
cur = conn.cursor()

# ---------- DATA ----------

def init_db():
    cur.execute("""
    CREATE TABLE IF NOT EXISTS chats (
        chat_id TEXT PRIMARY KEY,
        goal INTEGER
    );
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS users (
        user_id TEXT,
        chat_id TEXT,
        username TEXT,
        trainings TEXT[],
        PRIMARY KEY (user_id, chat_id)
    );
    """)

init_db()


# ---------- HELPERS ----------

def get_chat_data(chat_id):
    chat_id = str(chat_id)

    cur.execute("SELECT goal FROM chats WHERE chat_id=%s", (chat_id,))
    row = cur.fetchone()

    if row is None:
        cur.execute("INSERT INTO chats (chat_id, goal) VALUES (%s, %s)", (chat_id, None))

    return {"chat_id": chat_id, "goal": row[0] if row else None}

def set_goal(chat_id, goal):
    chat_id = str(chat_id)

    cur.execute("""
        INSERT INTO chats (chat_id, goal)
        VALUES (%s, %s)
        ON CONFLICT (chat_id)
        DO UPDATE SET goal = EXCLUDED.goal
    """, (chat_id, goal))

def get_user(chat_id, user_id):
    chat_id = str(chat_id)
    user_id = str(user_id)

    cur.execute("""
        SELECT username, trainings
        FROM users
        WHERE chat_id=%s AND user_id=%s
    """, (chat_id, user_id))

    return cur.fetchone()

def get_all_users(chat_id):
    chat_id = str(chat_id)

    cur.execute("""
        SELECT username, trainings
        FROM users
        WHERE chat_id=%s
    """, (chat_id,))

    return cur.fetchall()

def add_training_and_get_count(chat_id, user_id, username, today):
    cur.execute("""
        INSERT INTO users (user_id, chat_id, username, trainings)
        VALUES (%s, %s, %s, ARRAY[%s])
        ON CONFLICT (user_id, chat_id)
        DO UPDATE SET
            trainings = array_append(users.trainings, %s),
            username = EXCLUDED.username
        RETURNING array_length(trainings, 1)
    """, (user_id, chat_id, username, today, today))

    return cur.fetchone()[0]

def build_status(chat_id):
    chat_id = str(chat_id)
    cur.execute("SELECT goal FROM chats WHERE chat_id=%s", (chat_id,))
    goal = cur.fetchone()

    goal = goal[0] if goal else None
    users = get_all_users(chat_id)

    if goal is None:
        return "⚠️ Цель пока не установлена.\n\nЗадайте её и начнём движение вперёд 💪"
    if not users:
        return "😴 Пока нет ни одной тренировки.\n\nСамое время начать! 💪"
        
    leaderboard = sorted(users, key=lambda u: len(u[1]), reverse=True)

    text = f"🎯 Цель: {goal}\n\n🏆 Текущий прогресс:\n\n"

    for i, u in enumerate(leaderboard, start=1):
        count = len(u[1])
        bar = progress_bar(count, goal)
        percent = int((count / goal) * 100)
        text += f"{i}. {u[0]} — {count}/{goal}\n{bar} | {percent}%\n"

    return text

def progress_bar(count, goal):
    total_slots = 10

    if goal <= 0:
        return "⚪" * total_slots

    progress = count / goal

    full = int(progress * total_slots)  # fully completed (green)

    bar = []

    for i in range(total_slots):
        if i < full:
            bar.append("🟢")
        elif i == full and count > 0 and full < total_slots:
            bar.append("🟡")
        else:
            bar.append("⚪")

    return "".join(bar)


# ---------- START ----------

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [[
        InlineKeyboardButton("🎯 Новая цель", callback_data="new_goal"),
        InlineKeyboardButton("📊 Статус", callback_data="status")
    ]]
    await update.message.reply_text(
        "🏋️‍♂️ Добро пожаловать в тренировочный челлендж!\n\n"
        "Я помогу вам отслеживать прогресс и дойти до цели 💪\n"
        "Жми кнопку ниже и начинаем!",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


# ---------- STATUS ----------

async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    await update.message.reply_text(build_status(chat_id))


# ---------- NEW GOAL ----------

async def show_goal_buttons(chat_id, context):
    keyboard = [[
        InlineKeyboardButton("5", callback_data="5"),
        InlineKeyboardButton("10", callback_data="10"),
        InlineKeyboardButton("15", callback_data="15"),
        InlineKeyboardButton("20", callback_data="20"),
        InlineKeyboardButton("25", callback_data="25"),
        InlineKeyboardButton("30", callback_data="30"),
    ]]

    await context.bot.send_message(
        chat_id=chat_id,
        text="🎯 Сколько тренировок ставим целью на этот месяц?",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def new_goal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    await show_goal_buttons(chat_id, context)


# ---------- BUTTONS ----------

async def buttons(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    chat_id = query.message.chat_id

    if query.data == "new_goal":
        await show_goal_buttons(chat_id, context)
    elif query.data == "status":
        await query.message.reply_text(build_status(chat_id))
    elif query.data in ["5", "10", "15", "20", "25", "30"]:
        goal = int(query.data)
        set_goal(chat_id, goal)

        await query.message.reply_text(
            f"🎯 Цель установлена: {goal} тренировок!\n\nПогнали к результату 💪🔥"
        )

# ---------- TRAINING ----------

async def new_training(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = str(update.effective_chat.id)
    chat_data = get_chat_data(chat_id)
    goal = chat_data["goal"]

    if goal is None:
        await update.message.reply_text("Сначала установите цель.")
        return

    user_id = str(update.effective_user.id)
    username = update.effective_user.username or update.effective_user.first_name
    user = get_user(chat_id, user_id)
    today = datetime.date.today().isoformat()

    if user and today in user[1]:
        await update.message.reply_text("Сегодняшняя тренировка уже записана")
        return

    count = add_training_and_get_count(chat_id, user_id, username, today)

    remaining = max(goal - count, 0)

    bar = progress_bar(count, goal)
    percent = int((count / goal) * 100)

    if remaining == 0:
        await update.message.reply_text(
            f"🏆 {username}, сделано!\n\n"
            f"Цель достигнута: {count}/{goal} 🎯\n"
            f"{bar} | {percent}%\n\n"
            "Это было мощно 💪"
        )
    else:
        await update.message.reply_text(
            f"🔥 Отличная работа, {username}!\n"
            "+1 тренировка в копилку 💪\n\n"
            f"Прогресс: {count}/{goal}\n"
            f"Осталось: {remaining}\n"
            f"{bar} | {percent}%\n\n"
            "Только вперед! 🚀"
        )


# ---------- MONTH LEADERBOARD ----------

def get_leaderboard(chat_id):
    chat_id = str(chat_id)
    cur.execute("SELECT goal FROM chats WHERE chat_id=%s", (chat_id,))
    goal = cur.fetchone()

    goal = goal[0] if goal else None
    users = get_all_users(chat_id)

    leaderboard = sorted(users, key=lambda u: len(u[1]), reverse=True) if users else None
    return goal, leaderboard

def build_heatmap(trainings_list):
    today = datetime.date.today()
    year = today.year
    month = today.month
    first_weekday, days_in_month = calendar.monthrange(year, month)

    training_days = set()
    for date_str in trainings_list or []:
        try:
            training_date = datetime.date.fromisoformat(date_str)
        except ValueError:
            continue

        if training_date.year == year and training_date.month == month:
            training_days.add(training_date.day)

    lines = []
    week = []

    for _ in range(first_weekday):
        week.append("▫️")

    for day in range(1, days_in_month + 1):
        mark = "🟩" if day in training_days else "⬜"
        week.append(mark)

        if len(week) == 7:
            lines.append(" ".join(week))
            week = []

    if week:
        week.extend(["  "] * (7 - len(week)))
        lines.append(" ".join(week))

    return "\n".join(lines)


def build_leaderboard_text(goal, leaderboard):
    if not leaderboard or not goal:
        return None

    medals = ["🥇", "🥈", "🥉"]

    text = "🏆 Итоги месяца\n\n"

    for i, u in enumerate(leaderboard):
        place = medals[i] if i < 3 else f"{i+1}️."

        #u[0] is username, u[1] is trainings list
        text += f"{place} {u[0]} — {len(u[1])}"
        text += f"/{goal}\n   {progress_bar(len(u[1]), goal)} | {int((len(u[1]) / goal) * 100)}%\n"
        text += build_heatmap(u[1])
        text += "\n"

    return text

def is_last_day_of_month():
    today = datetime.date.today()
    return today.day == calendar.monthrange(today.year, today.month)[1]

def is_first_day_of_month():
    today = datetime.date.today()
    return today.day == 1

async def send_monthly_leaderboard(context):
    if not is_last_day_of_month():
        return

    with conn.cursor() as cur:
        cur.execute("SELECT DISTINCT chat_id FROM users")
        chats = cur.fetchall()

    for (chat_id,) in chats:
        goal, rows = get_leaderboard(chat_id)
        text = build_leaderboard_text(goal, rows)

        if not text:
            continue

        await context.bot.send_message(
            chat_id=chat_id,
            text=text
        )

# ---------- MONTH RESET ----------

async def reset_month(context: ContextTypes.DEFAULT_TYPE):
    if not is_first_day_of_month():
        return

    # получаем все chat_id
    cur.execute("""SELECT DISTINCT chat_id FROM chats""")
    chats = cur.fetchall()

    cur.execute("""DELETE FROM users""")
    cur.execute("""UPDATE chats SET goal = NULL""")

    # уведомляем чаты
    for (chat_id,) in chats:
        await context.bot.send_message(
            chat_id=chat_id,
            text=(
                "🎉 Новый месяц начался! Время для новых подвигов!\n\n"
                "Установите новую цель командой: /new_goal"
            )
        )


# ---------- COMMANDS ----------

async def set_commands(app):
    commands = [
        BotCommand("start", "Запустить бота"),
        BotCommand("new_goal", "Установить цель на месяц"),
        BotCommand("status", "Показать статус"),
        BotCommand("new_training_completed", "Записать тренировку"),
    ]
    await app.bot.set_my_commands(commands)


# ---------- MAIN ----------

def main():
    app = ApplicationBuilder().token(TOKEN).build()
    app.post_init = set_commands

    job_queue = app.job_queue
    job_queue.run_daily(send_monthly_leaderboard, time=datetime.time(hour=20, minute=0))
    job_queue.run_daily(reset_month, time=datetime.time(hour=8, minute=0))

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("status", status))
    app.add_handler(CommandHandler("new_goal", new_goal))
    app.add_handler(CommandHandler("new_training_completed", new_training))

    app.add_handler(CallbackQueryHandler(buttons))

    app.run_polling()


if __name__ == "__main__":
    main()
import os
import datetime
import psycopg2

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, BotCommand
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ContextTypes,
    filters,
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
        text += f"{i}. {u[0]} — {len(u[1])}/{goal}\n"

    return text


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


# ---------- TEXT INPUT ----------

# async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
#     chat_id = str(update.effective_chat.id)
#     if awaiting_goal_chats.get(chat_id):
#         try:
#             goal = int(update.message.text)
#             chat_data = get_chat_data(chat_id)
#             chat_data["goal"] = goal
#             save_data(data)
#             awaiting_goal_chats[chat_id] = False
#             await update.message.reply_text(f"Цель установлена: {goal} тренировок.")
#         except:
#             await update.message.reply_text("Введите число.")


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

    if remaining == 0:
        await update.message.reply_text(
            f"🏆 {username}, сделано!\n\n"
            f"Цель достигнута: {count}/{goal} 🎯\n"
            "Это было мощно 💪\n"
            "Впереди новые цели!"
        )
    else:
        await update.message.reply_text(
            f"🔥 Отличная работа, {username}!\n\n"
            "+1 тренировка в копилку 💪\n"
            f"Прогресс: {count}/{goal}\n"
            f"Осталось: {remaining}\n\n"

            "Только вперед! 🚀"
        )


# ---------- MONTH LEADERBOARD ----------

# async def month_summary(context: ContextTypes.DEFAULT_TYPE):
#     for chat_id_str, chat_data in data["chats"].items():
#         chat_id = int(chat_id_str)
#         goal = chat_data["goal"]
#         users = chat_data["users"]

#         if not users:
#             continue

#         leaderboard = sorted(users.values(), key=lambda u: len(u["trainings"]), reverse=True)
#         text = "🏆 Итоги месяца\n\n"
#         for i, u in enumerate(leaderboard, start=1):
#             count = len(u["trainings"])
#             text += f"{i}. {u['username']} — {count}\n"

#         if goal:
#             winners = [u["username"] for u in leaderboard if len(u["trainings"]) >= goal]
#             if winners:
#                 text += "\n🎯 Цель достигли:\n"
#                 for w in winners:
#                     text += f"{w}\n"

#         await context.bot.send_message(chat_id=chat_id, text=text)


# ---------- MONTH RESET ----------

# async def reset_month(context: ContextTypes.DEFAULT_TYPE):
#     for chat_id_str, chat_data in data["chats"].items():
#         chat_id = int(chat_id_str)
#         chat_data["goal"] = None
#         chat_data["users"] = {}
#         await context.bot.send_message(
#             chat_id=chat_id,
#             text="Новый месяц! 🎉\n\nУстановите новую цель командой /new-goal"
#         )
#     save_data(data)


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

    # job_queue = app.job_queue
    # # итог месяца в 19:00 последнего дня месяца
    # job_queue.run_daily(month_summary, time=datetime.time(hour=19, minute=0))
    # # сброс 1 числа месяца в 08:00
    # job_queue.run_daily(reset_month, time=datetime.time(hour=8, minute=0))

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("status", status))
    app.add_handler(CommandHandler("new_goal", new_goal))
    app.add_handler(CommandHandler("new_training_completed", new_training))

    app.add_handler(CallbackQueryHandler(buttons))
    # app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler))

    app.run_polling()


if __name__ == "__main__":
    main()
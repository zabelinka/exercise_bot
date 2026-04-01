import json
import os
import datetime

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
DATA_FILE = "data.json"

awaiting_goal = False


# ---------- DATA ----------

def load_data():

    if not os.path.exists(DATA_FILE):
        return {
            "goal": None,
            "chat_id": None,
            "users": {}
        }

    with open(DATA_FILE, "r") as f:
        return json.load(f)


def save_data(data):

    with open(DATA_FILE, "w") as f:
        json.dump(data, f, indent=2)


data = load_data()


# ---------- STATUS ----------

def build_status():

    goal = data["goal"]

    if goal is None:
        return "Цель ещё не установлена."

    users = data["users"]

    if not users:
        return "Пока нет тренировок."

    leaderboard = sorted(
        users.values(),
        key=lambda u: len(u["trainings"]),
        reverse=True
    )

    text = "Статус:\n\n"

    for u in leaderboard:

        count = len(u["trainings"])

        text += f'{u["username"]}: {count}/{goal}\n'

    return text


# ---------- START ----------

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):

    data["chat_id"] = update.effective_chat.id
    save_data(data)

    keyboard = [[
        InlineKeyboardButton("Новая цель", callback_data="new_goal"),
        InlineKeyboardButton("Статус", callback_data="status")
    ]]

    await update.message.reply_text(
        "Я бот - челленж тренировок!",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


# ---------- STATUS ----------

async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):

    await update.message.reply_text(build_status())


# ---------- NEW GOAL ----------

async def new_goal(update: Update, context: ContextTypes.DEFAULT_TYPE):

    global awaiting_goal

    awaiting_goal = True

    await update.message.reply_text(
        "Сколько тренировок вы хотите сделать в этом месяце?"
    )


# ---------- BUTTONS ----------

async def buttons(update: Update, context: ContextTypes.DEFAULT_TYPE):

    global awaiting_goal

    query = update.callback_query
    await query.answer()

    if query.data == "new_goal":

        awaiting_goal = True

        await query.message.reply_text(
            "Сколько тренировок вы хотите сделать в этом месяце?"
        )

    elif query.data == "status":

        await query.message.reply_text(build_status())


# ---------- TEXT INPUT ----------

async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):

    global awaiting_goal

    if awaiting_goal:

        try:

            goal = int(update.message.text)

            data["goal"] = goal
            save_data(data)

            awaiting_goal = False

            await update.message.reply_text(
                f"Цель установлена: {goal} тренировок."
            )

        except:

            await update.message.reply_text("Введите число.")


# ---------- TRAINING ----------

async def new_training(update: Update, context: ContextTypes.DEFAULT_TYPE):

    user = update.effective_user
    user_id = str(user.id)
    username = user.username or user.first_name

    goal = data["goal"]

    if goal is None:

        await update.message.reply_text(
            "Сначала установите цель."
        )

        return

    today = datetime.date.today().isoformat()

    users = data["users"]

    if user_id not in users:

        users[user_id] = {
            "username": username,
            "trainings": []
        }

    if today in users[user_id]["trainings"]:

        await update.message.reply_text(
            "сегодняшняя тренировка уже записана"
        )

        return

    users[user_id]["trainings"].append(today)

    save_data(data)

    count = len(users[user_id]["trainings"])

    remaining = max(goal - count, 0)

    await update.message.reply_text(
        f"Молодец, {username}! Ещё одна тренировка сделана, так держать!\n"
        f"Выполнено {count}/{goal}. Осталось {remaining} тренировок!"
    )


# ---------- MONTH LEADERBOARD ----------

async def month_summary(context: ContextTypes.DEFAULT_TYPE):

    chat_id = data["chat_id"]

    if chat_id is None:
        return

    users = data["users"]
    goal = data["goal"]

    if not users:
        return

    leaderboard = sorted(
        users.values(),
        key=lambda u: len(u["trainings"]),
        reverse=True
    )

    text = "🏆 Итоги месяца\n\n"

    for i, u in enumerate(leaderboard, start=1):

        count = len(u["trainings"])

        text += f"{i}. {u['username']} — {count}\n"

    if goal:

        winners = [
            u["username"]
            for u in leaderboard
            if len(u["trainings"]) >= goal
        ]

        if winners:

            text += "\n🎯 Цель достигли:\n"

            for w in winners:
                text += f"{w}\n"

    await context.bot.send_message(chat_id=chat_id, text=text)


# ---------- MONTH RESET ----------

async def reset_month(context: ContextTypes.DEFAULT_TYPE):

    chat_id = data["chat_id"]

    if chat_id is None:
        return

    data["goal"] = None
    data["users"] = {}

    save_data(data)

    await context.bot.send_message(
        chat_id=chat_id,
        text="Новый месяц! 🎉\n\nУстановите новую цель командой /new-goal"
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
    
    # job_queue = app.job_queue

    # # последний день месяца в 19:00
    # job_queue.run_daily(
    #     month_summary,
    #     time=datetime.time(hour=19, minute=0),
    # )

    # # 1 число месяца в 08:00
    # job_queue.run_daily(
    #     reset_month,
    #     time=datetime.time(hour=8, minute=0),
    # )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("status", status))
    app.add_handler(CommandHandler("new_goal", new_goal))
    app.add_handler(CommandHandler("new_training_completed", new_training))

    app.add_handler(CallbackQueryHandler(buttons))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler))

    app.run_polling()


if __name__ == "__main__":
    main()
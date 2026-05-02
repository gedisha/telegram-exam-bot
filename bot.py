import logging
import random
import json
import os
import sqlite3
import time
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
)
from telegram.request import HTTPXRequest
from dotenv import load_dotenv

# ============================================================================
# CONFIGURATION
# ============================================================================
load_dotenv()
TOKEN = os.getenv("BOT_TOKEN")

# Replace with your actual Telegram user ID (you can get it from @userinfobot)
ADMIN_ID = 123456789  # <-- CHANGE THIS TO YOUR USER ID

# Enable logging to file and console
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
    handlers=[
        logging.FileHandler("bot_activity.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# ============================================================================
# DATABASE FUNCTIONS
# ============================================================================
DB_NAME = "quiz_bot.db"

def init_db():
    """Create tables if they don't exist."""
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY,
        username TEXT,
        first_name TEXT,
        last_name TEXT,
        joined_date INTEGER
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS quiz_attempts (
        attempt_id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        program TEXT,
        course TEXT,
        score INTEGER,
        total INTEGER,
        start_time INTEGER,
        end_time INTEGER
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS answers (
        answer_id INTEGER PRIMARY KEY AUTOINCREMENT,
        attempt_id INTEGER,
        question_text TEXT,
        user_answer TEXT,
        is_correct INTEGER
    )''')
    conn.commit()
    conn.close()
    logger.info("Database initialized.")

def add_user(user_id, username, first_name, last_name):
    """Add a new user if not already present."""
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("INSERT OR IGNORE INTO users (user_id, username, first_name, last_name, joined_date) VALUES (?, ?, ?, ?, ?)",
              (user_id, username or "", first_name or "", last_name or "", int(time.time())))
    conn.commit()
    conn.close()

def start_quiz_attempt(user_id, program, course):
    """Create a new quiz attempt record and return its attempt_id."""
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("INSERT INTO quiz_attempts (user_id, program, course, score, total, start_time, end_time) VALUES (?, ?, ?, 0, 0, ?, NULL)",
              (user_id, program, course, int(time.time())))
    attempt_id = c.lastrowid
    conn.commit()
    conn.close()
    return attempt_id

def end_quiz_attempt(attempt_id, score, total):
    """Update the attempt with final score and end time."""
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("UPDATE quiz_attempts SET score = ?, total = ?, end_time = ? WHERE attempt_id = ?",
              (score, total, int(time.time()), attempt_id))
    conn.commit()
    conn.close()

def save_answer(attempt_id, question_text, user_answer, is_correct):
    """Record a single answer."""
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("INSERT INTO answers (attempt_id, question_text, user_answer, is_correct) VALUES (?, ?, ?, ?)",
              (attempt_id, question_text[:250], user_answer, 1 if is_correct else 0))
    conn.commit()
    conn.close()

# ============================================================================
# LOAD QUESTIONS FROM JSON FILES
# ============================================================================
QUESTIONS = {}

def load_all_questions(base_path="questions"):
    """Load all JSON files from program subfolders."""
    data = {}
    if not os.path.exists(base_path):
        logger.warning(f"Folder '{base_path}' not found. No external questions loaded.")
        return data

    for program in os.listdir(base_path):
        program_path = os.path.join(base_path, program)
        if not os.path.isdir(program_path):
            continue
        data[program] = {}
        for filename in os.listdir(program_path):
            if filename.endswith(".json"):
                course_name = filename[:-5]
                filepath = os.path.join(program_path, filename)
                try:
                    with open(filepath, "r", encoding="utf-8") as f:
                        questions_list = json.load(f)
                    if isinstance(questions_list, list) and len(questions_list) > 0:
                        data[program][course_name] = questions_list
                        logger.info(f"Loaded {len(questions_list)} questions for {program} / {course_name}")
                    else:
                        logger.warning(f"Skipped {filepath} – empty or invalid.")
                except Exception as e:
                    logger.error(f"Error loading {filepath}: {e}")
    return data

QUESTIONS = load_all_questions()
if not any(QUESTIONS.values()):
    logger.warning("No courses/questions loaded. Add JSON files in 'questions/' folder.")

# ============================================================================
# USER SESSION DATA
# ============================================================================
user_data = {}

# ============================================================================
# COMMAND HANDLERS
# ============================================================================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    add_user(user.id, user.username, user.first_name, user.last_name)
    await update.message.reply_text(
        "🎓 **AgEc, ABVM & RDAE Exit Exam Prep Bot**\n"
        "Created by Gedisha\n\n"
        "Use /quiz to start.\n"
        "Select your program, then a course, then answer questions.\n\n"
        "Good luck!",
        parse_mode="Markdown"
    )

async def quiz_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("🌾 Agricultural Economics (AgEc)", callback_data="prog_AgEc")],
        [InlineKeyboardButton("📦 Agribusiness & Value Chain (ABVM)", callback_data="prog_ABVM")],
        [InlineKeyboardButton("🏞️ Rural Dev & Extension (RDAE)", callback_data="prog_RDAE")],
    ]
    await update.message.reply_text(
        "Select your program:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin-only command to show bot usage statistics."""
    user_id = update.effective_user.id
    if user_id != ADMIN_ID:
        await update.message.reply_text("⛔ Unauthorized.")
        return

    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM users")
    total_users = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM quiz_attempts")
    total_attempts = c.fetchone()[0]
    c.execute("SELECT AVG(score * 1.0 / total) FROM quiz_attempts WHERE total > 0")
    avg_score = c.fetchone()[0] or 0
    conn.close()

    await update.message.reply_text(
        f"📊 **Bot Statistics**\n\n"
        f"👥 Total users: {total_users}\n"
        f"📝 Total quizzes taken: {total_attempts}\n"
        f"📈 Average score: {avg_score:.1%}",
        parse_mode="Markdown"
    )

# ============================================================================
# CALLBACK HANDLERS
# ============================================================================
async def program_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    program = query.data.split("_")[1]
    context.user_data["selected_program"] = program

    courses = list(QUESTIONS.get(program, {}).keys())
    if not courses:
        await query.edit_message_text(f"No courses available for {program}. Contact admin.")
        return

    keyboard = [[InlineKeyboardButton(course, callback_data=f"course_{course}")] for course in courses]
    keyboard.append([InlineKeyboardButton("🔙 Back to programs", callback_data="back_to_programs")])
    await query.edit_message_text(
        f"✅ Program: {program}\n\nSelect a course:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def course_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    course = query.data.split("_", 1)[1]
    program = context.user_data.get("selected_program")
    if not program:
        await query.edit_message_text("Session expired. Use /quiz to start over.")
        return

    course_questions = QUESTIONS.get(program, {}).get(course, [])
    if not course_questions:
        await query.edit_message_text(
            f"❌ No questions available for **{course}** yet.\n"
            "The question bank is being prepared. Please check back later.",
            parse_mode="Markdown"
        )
        return

    # Record the user (if new) and start a quiz attempt
    user = update.effective_user
    add_user(user.id, user.username, user.first_name, user.last_name)
    attempt_id = start_quiz_attempt(user.id, program, course)

    # Shuffle questions and store session
    qids = list(range(len(course_questions)))
    random.shuffle(qids)
    user_id = user.id
    user_data[user_id] = {
        "program": program,
        "course": course,
        "questions": course_questions,
        "order": qids,
        "current_index": 0,
        "score": 0,
        "total": len(course_questions),
        "attempt_id": attempt_id,
    }

    await query.edit_message_text(f"✅ Course: {course}\nStarting quiz...")
    await send_question(update, context, user_id)

async def send_question(update: Update, context: ContextTypes.DEFAULT_TYPE, user_id: int):
    data = user_data.get(user_id)
    if not data or data["current_index"] >= data["total"]:
        await finalize_quiz(update, context, user_id)
        return

    idx = data["current_index"]
    qid = data["order"][idx]
    q = data["questions"][qid]

    keyboard = []
    for i, opt in enumerate(q["options"]):
        keyboard.append([InlineKeyboardButton(opt, callback_data=f"ans_{qid}_{i}")])
    reply_markup = InlineKeyboardMarkup(keyboard)

    text = f"**{data['course']}** – Q{idx+1}/{data['total']}\n\n{q['question']}"
    await context.bot.send_message(chat_id=user_id, text=text, reply_markup=reply_markup, parse_mode="Markdown")

async def handle_answer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    data = user_data.get(user_id)
    if not data:
        await query.edit_message_text("Session expired. Use /quiz to start over.")
        return

    parts = query.data.split("_")
    if len(parts) != 3:
        return
    qid = int(parts[1])
    selected = int(parts[2])

    q = data["questions"][qid]
    is_correct = (selected == q["correct"])
    if is_correct:
        data["score"] += 1
        feedback = f"✅ **Correct!**\n\n{q['explanation']}"
    else:
        correct_text = q["options"][q["correct"]]
        feedback = f"❌ **Incorrect.**\nCorrect answer: {correct_text}\n\n{q['explanation']}"

    # Save the answer to database
    save_answer(data["attempt_id"], q["question"], q["options"][selected], is_correct)

    data["current_index"] += 1
    await query.edit_message_text(feedback, parse_mode="Markdown")

    if data["current_index"] >= data["total"]:
        await finalize_quiz(update, context, user_id)
    else:
        await send_question(update, context, user_id)

async def finalize_quiz(update: Update, context: ContextTypes.DEFAULT_TYPE, user_id: int):
    data = user_data.pop(user_id, None)
    if data:
        # Update the quiz attempt with final score
        end_quiz_attempt(data["attempt_id"], data["score"], data["total"])
        await context.bot.send_message(
            chat_id=user_id,
            text=f"🏆 **Quiz finished!**\n"
                 f"Course: {data['course']}\n"
                 f"Score: {data['score']}/{data['total']}\n\n"
                 f"Use /quiz to try another course.\n"
                 f"Created by Gedisha",
            parse_mode="Markdown"
        )

async def show_score(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    data = user_data.get(user_id)
    if not data:
        await update.message.reply_text("No active quiz. Start one with /quiz.")
    else:
        await update.message.reply_text(f"Current score: {data['score']}/{data['total']}")

async def back_to_programs(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data.clear()
    keyboard = [
        [InlineKeyboardButton("🌾 Agricultural Economics (AgEc)", callback_data="prog_AgEc")],
        [InlineKeyboardButton("📦 Agribusiness & Value Chain (ABVM)", callback_data="prog_ABVM")],
        [InlineKeyboardButton("🏞️ Rural Dev & Extension (RDAE)", callback_data="prog_RDAE")],
    ]
    await query.edit_message_text(
        "Select your program:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

# ============================================================================
# MAIN
# ============================================================================
def main():
    # Initialize database
    init_db()

    # Set up bot with higher timeouts to avoid TimedOut
    request = HTTPXRequest(connect_timeout=30.0, read_timeout=30.0, write_timeout=30.0)
    app = Application.builder().token(TOKEN).request(request).build()

    # Command handlers
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("quiz", quiz_command))
    app.add_handler(CommandHandler("score", show_score))
    app.add_handler(CommandHandler("stats", stats_command))

    # Callback handlers
    app.add_handler(CallbackQueryHandler(program_selected, pattern="^prog_"))
    app.add_handler(CallbackQueryHandler(course_selected, pattern="^course_"))
    app.add_handler(CallbackQueryHandler(handle_answer, pattern="^ans_"))
    app.add_handler(CallbackQueryHandler(back_to_programs, pattern="^back_to_programs$"))

    logger.info("Bot is running...")
    app.run_polling()

if __name__ == "__main__":
    main()
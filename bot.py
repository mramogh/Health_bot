import os
import logging
import json
import base64
import httpx
from datetime import datetime, date
from pathlib import Path
from telegram import Update
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    filters, ContextTypes
)
from apscheduler.schedulers.asyncio import AsyncIOScheduler
import pytz

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ── Config ──────────────────────────────────────────────────────────────────
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "YOUR_TELEGRAM_BOT_TOKEN")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "YOUR_GEMINI_API_KEY")
YOUR_CHAT_ID   = os.environ.get("CHAT_ID", "YOUR_TELEGRAM_CHAT_ID")  # your personal chat ID
IST = pytz.timezone("Asia/Kolkata")

LOG_FILE = Path("health_log.json")

SYSTEM_PROMPT = """You are Amogh's personal health coach bot on Telegram. 
Amogh is 21 years old, 125kg, 6.5 feet tall, has Type 2 Diabetes, and is trying to lose weight.
He plays badminton every morning. He is from Jaipur, India.
- Always be warm, motivating, and personal. Call him Amogh.
- For food analysis: give calories, protein, carbs, fat, glycemic impact (low/medium/high for diabetes), and a 1-line tip.
- For ingredient suggestions: give 2-3 Indian diabetic-friendly meal ideas with quick recipe and calories.
- Keep responses concise and practical. Use simple language.
- Always remind about blood sugar awareness when relevant."""

# ── Logging helpers ──────────────────────────────────────────────────────────
def load_log():
    if LOG_FILE.exists():
        return json.loads(LOG_FILE.read_text())
    return {}

def save_log(data):
    LOG_FILE.write_text(json.dumps(data, indent=2))

def log_today(key, value):
    data = load_log()
    today = str(date.today())
    if today not in data:
        data[today] = {"meals": [], "water": 0, "workout": False, "calories": 0}
    if key == "meal":
        data[today]["meals"].append(value)
        data[today]["calories"] += value.get("calories", 0)
    else:
        data[today][key] = value
    save_log(data)

def get_today_log():
    data = load_log()
    today = str(date.today())
    return data.get(today, {"meals": [], "water": 0, "workout": False, "calories": 0})

# ── Gemini API call ───────────────────────────────────────────────────────────
async def ask_gemini(prompt: str, image_b64: str = None, mime: str = "image/jpeg") -> str:
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={GEMINI_API_KEY}"
    parts = []
    if image_b64:
        parts.append({"inline_data": {"mime_type": mime, "data": image_b64}})
    parts.append({"text": prompt})

    payload = {
        "system_instruction": {"parts": [{"text": SYSTEM_PROMPT}]},
        "contents": [{"parts": parts}],
        "generationConfig": {"maxOutputTokens": 500, "temperature": 0.7}
    }
    async with httpx.AsyncClient(timeout=30) as client:
        r = await client.post(url, json=payload)
        r.raise_for_status()
        return r.json()["candidates"][0]["content"]["parts"][0]["text"]

# ── Scheduled messages ────────────────────────────────────────────────────────
async def send_wakeup(app):
    msgs = [
        "🌅 Good morning Amogh! Badminton in 25 minutes.\n\nHave a banana or 2 biscuits before you go — don't play empty stomach with diabetes!\n\nYou've got this. Let's go! 💪",
        "☀️ Rise and shine Amogh! Court is calling you.\n\nEat something small before you leave. Blood sugar first, game second! 🏸",
        "🏸 Good morning champ! Time to hit the court.\n\nRemember — juice box in your bag in case blood sugar drops. Now go crush it! 💥",
    ]
    import random
    await app.bot.send_message(chat_id=YOUR_CHAT_ID, text=random.choice(msgs))

async def send_workout_checkin(app):
    await app.bot.send_message(
        chat_id=YOUR_CHAT_ID,
        text="🏸 How was badminton today Amogh?\n\nReply with:\n✅ Done - [how it went]\n❌ Missed - [reason]\n\nNo judgment, just tracking! 😊"
    )

async def send_water_reminder(app):
    log = get_today_log()
    glasses = log.get("water", 0)
    await app.bot.send_message(
        chat_id=YOUR_CHAT_ID,
        text=f"💧 Water check! You've had {glasses} glasses today.\n\nDrink one right now! Target is 12-14 glasses. Reply 'water' to log it."
    )

async def send_daily_summary(app):
    log = get_today_log()
    calories = log.get("calories", 0)
    water = log.get("water", 0)
    workout = log.get("workout", False)
    meals = len(log.get("meals", []))
    cal_status = "🟢 Great!" if calories < 2100 else ("🟡 A little high" if calories < 2400 else "🔴 Over target")
    water_status = "🟢 Great!" if water >= 10 else ("🟡 Drink more" if water >= 6 else "🔴 Too low")
    workout_status = "🟢 Done!" if workout else "🔴 Missed today"

    summary = f"""📊 *Daily Summary — {date.today().strftime('%d %b %Y')}*

🍽 Meals logged: {meals}
🔥 Calories: ~{calories} kcal {cal_status}
💧 Water: {water} glasses {water_status}
🏸 Workout: {workout_status}

{"Well done Amogh! Solid day. Keep this up and the results will come fast! 🚀" if workout and calories < 2200 else "Tomorrow is a new chance. Sleep well and start fresh! 💪"}

Good night! 🌙"""
    await app.bot.send_message(chat_id=YOUR_CHAT_ID, text=summary, parse_mode="Markdown")

# ── Command handlers ──────────────────────────────────────────────────────────
async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    await update.message.reply_text(
        f"Hey Amogh! Your health bot is live! 💪\n\n"
        f"Here is what I can do:\n"
        f"📸 Send a food photo → I will calculate calories\n"
        f"🥘 Type 'cook: [ingredients]' → I will suggest diabetic-friendly meals\n"
        f"💧 Type 'water' → Log a glass of water\n"
        f"✅ Type 'done' → Log today's workout\n"
        f"📊 Type 'summary' → See today's stats\n"
        f"❓ Ask me anything about diet or fitness!\n\n"
        f"Your chat ID is: {chat_id}\n"
        f"Make sure this is saved as your CHAT_ID in Railway!"
    )

async def handle_text(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip().lower()

    # Water logging
    if text in ["water", "💧", "water done"]:
        log = get_today_log()
        glasses = log.get("water", 0) + 1
        log_today("water", glasses)
        await update.message.reply_text(f"💧 Logged! That's {glasses} glasses today. Keep going!")
        return

    # Workout done
    if text in ["done", "workout done", "✅", "played", "finished"]:
        log_today("workout", True)
        await update.message.reply_text("🏸 Workout logged! Amazing Amogh. Your blood sugar thanks you too! 💪")
        return

    # Daily summary
    if text in ["summary", "stats", "today"]:
        log = get_today_log()
        calories = log.get("calories", 0)
        water = log.get("water", 0)
        workout = log.get("workout", False)
        meals_count = len(log.get("meals", []))
        await update.message.reply_text(
            f"📊 Today so far:\n\n"
            f"🍽 Meals: {meals_count}\n"
            f"🔥 Calories: ~{calories} kcal\n"
            f"💧 Water: {water} glasses\n"
            f"🏸 Workout: {'✅ Done' if workout else '❌ Not yet'}"
        )
        return

    # Ingredient-based meal suggestion
    if text.startswith("cook:") or text.startswith("cook "):
        ingredients = text.replace("cook:", "").replace("cook ", "").strip()
        await update.message.reply_text("🍳 Let me think of something tasty and healthy for you...")
        prompt = f"Amogh has these ingredients: {ingredients}. Suggest 2-3 Indian diabetic-friendly meals he can make. For each: meal name, quick 3-step recipe, approximate calories, and glycemic rating."
        reply = await ask_gemini(prompt)
        await update.message.reply_text(reply)
        return

    # General health question — pass to Gemini
    await update.message.reply_text("🤔 Let me answer that...")
    reply = await ask_gemini(f"Amogh asks: {update.message.text}")
    await update.message.reply_text(reply)

async def handle_photo(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("📸 Got your food photo! Analysing calories...")
    photo = await update.message.photo[-1].get_file()
    photo_bytes = await photo.download_as_bytearray()
    image_b64 = base64.b64encode(photo_bytes).decode()

    prompt = """Analyse this food photo for Amogh who has Type 2 Diabetes and is trying to lose weight.
Provide:
1. 🍽 What the food appears to be
2. 🔥 Estimated calories (give a range)
3. 💪 Protein / 🍞 Carbs / 🧈 Fat (rough grams)
4. 🩸 Glycemic impact: Low / Medium / High (with brief reason)
5. ✅ One thing that's good about this meal
6. ⚠️ One thing to watch out for
7. 💡 One small suggestion to make it healthier

Keep it friendly and encouraging!"""

    try:
        reply = await ask_gemini(prompt, image_b64)
        # Try to extract calories for logging
        try:
            import re
            cal_match = re.search(r'(\d+)\s*[-–]\s*(\d+)\s*cal', reply, re.IGNORECASE)
            if cal_match:
                avg_cal = (int(cal_match.group(1)) + int(cal_match.group(2))) // 2
                log_today("meal", {"time": datetime.now().strftime("%H:%M"), "calories": avg_cal, "description": "photo meal"})
        except:
            pass
        await update.message.reply_text(reply)
    except Exception as e:
        logger.error(f"Gemini error: {e}")
        await update.message.reply_text("Sorry, couldn't analyse the photo. Try sending it again!")

# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    app = Application.builder().token(TELEGRAM_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    scheduler = AsyncIOScheduler(timezone=IST)
    scheduler.add_job(send_wakeup,          "cron", hour=5,  minute=50, args=[app])
    scheduler.add_job(send_workout_checkin, "cron", hour=7,  minute=30, args=[app])
    scheduler.add_job(send_water_reminder,  "cron", hour=8,  minute=0,  args=[app])
    scheduler.add_job(send_water_reminder,  "cron", hour=10, minute=0,  args=[app])
    scheduler.add_job(send_water_reminder,  "cron", hour=12, minute=0,  args=[app])
    scheduler.add_job(send_water_reminder,  "cron", hour=14, minute=0,  args=[app])
    scheduler.add_job(send_water_reminder,  "cron", hour=16, minute=0,  args=[app])
    scheduler.add_job(send_water_reminder,  "cron", hour=18, minute=0,  args=[app])
    scheduler.add_job(send_daily_summary,   "cron", hour=21, minute=30, args=[app])
    scheduler.start()

    logger.info("🤖 Amogh's Health Bot is running!")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()

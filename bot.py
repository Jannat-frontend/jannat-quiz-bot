import os
import json
import logging
import hashlib
import random
import asyncio
import requests
from datetime import datetime
from threading import Thread

from flask import Flask, request, jsonify
from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, ConversationHandler, ContextTypes, filters

import razorpay

# ========== CONFIGURATION ==========
TOKEN = os.environ.get("BOT_TOKEN")
RAZORPAY_KEY_ID = os.environ.get("RAZORPAY_KEY_ID")
RAZORPAY_KEY_SECRET = os.environ.get("RAZORPAY_KEY_SECRET")
ADMIN_ID = int(os.environ.get("ADMIN_ID", "0"))

# States
PHONE_REG, PASSWORD_REG, UPI_INPUT = range(3)

# Logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ========== RAZORPAY ==========
razorpay_client = razorpay.Client(auth=(RAZORPAY_KEY_ID, RAZORPAY_KEY_SECRET))

# ========== FLASK WEBHOOK ==========
web_app = Flask(__name__)

# Store bot application for webhook
telegram_app = None

# ========== TELEGRAM WEBHOOK ROUTE ==========
@web_app.route("/webhook", methods=["POST"])
def telegram_webhook():
    """Receive updates from Telegram via webhook"""
    try:
        if telegram_app:
            update = Update.de_json(request.get_json(), telegram_app.bot)
            # Process update asynchronously
            asyncio.run_coroutine_threadsafe(
                telegram_app.process_update(update),
                asyncio.get_event_loop()
            )
        return "OK", 200
    except Exception as e:
        logger.error(f"Telegram webhook error: {e}")
        return "Error", 500

# ========== RAZORPAY WEBHOOK ROUTE ==========
@web_app.route("/razorpay-webhook", methods=["POST"])
def razorpay_webhook():
    """Handle Razorpay payment confirmation"""
    try:
        payload = request.get_json()
        logger.info(f"🔔 RAZORPAY WEBHOOK RECEIVED")
        
        event = payload.get("event", "")
        
        if event not in ["payment_link.paid", "payment.captured"]:
            logger.info(f"Ignored event: {event}")
            return jsonify({"status": "ignored"}), 200
        
        # Extract telegram_id
        if event == "payment_link.paid":
            payment_link = payload.get("payload", {}).get("payment_link", {}).get("entity", {})
            notes = payment_link.get("notes", {})
            telegram_id = notes.get("telegram_id")
            amount = payment_link.get("amount", 0) / 100
        else:
            payment = payload.get("payload", {}).get("payment", {}).get("entity", {})
            notes = payment.get("notes", {})
            telegram_id = notes.get("telegram_id")
            amount = payment.get("amount", 0) / 100
        
        logger.info(f"💰 Payment: TG ID={telegram_id}, Amount=₹{amount}")
        
        if not telegram_id:
            logger.warning("❌ No telegram_id in payment notes")
            return jsonify({"error": "No telegram_id"}), 200
        
        # Mark user as paid in JSON file
        users = load_data("users.json")
        if str(telegram_id) in users:
            users[str(telegram_id)]["payment_completed"] = True
            save_data("users.json", users)
            logger.info(f"✅ User {telegram_id} marked as paid")
            
            # Send confirmation message via Telegram API
            try:
                send_url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
                send_data = {
                    "chat_id": int(telegram_id),
                    "text": "✅ *Payment Confirmed!* 🎉\n\n🔓 Press '🔓 Start Quiz' to play 3 questions and win ₹1000!",
                    "parse_mode": "Markdown"
                }
                response = requests.post(send_url, json=send_data)
                logger.info(f"✅ Confirmation sent to user {telegram_id}")
            except Exception as e:
                logger.error(f"Failed to send message: {e}")
        else:
            logger.warning(f"User {telegram_id} not found in database")
        
        return jsonify({"status": "success"}), 200
        
    except Exception as e:
        logger.error(f"Webhook error: {e}")
        return jsonify({"error": str(e)}), 500

# ========== PAYMENT SUCCESS PAGE ==========
@web_app.route("/payment-success", methods=["GET"])
def payment_success():
    return """
    <!DOCTYPE html>
    <html>
    <head><title>Payment Received</title></head>
    <body style="font-family: Arial; text-align: center; padding: 50px;">
        <h1>✅ Payment Received!</h1>
        <h2>Your quiz is being unlocked...</h2>
        <p>Please return to Telegram and press <strong>Start Quiz</strong>.</p>
        <p>You will receive a confirmation message shortly.</p>
        <hr>
        <p>Jannat Foundation Quiz</p>
    </body>
    </html>
    """

@web_app.route("/webhook-test", methods=["GET"])
def webhook_test():
    return jsonify({"status": "alive", "message": "Webhook endpoints are working"})

@web_app.route("/")
def home():
    return "Jannat Quiz Bot is running! Webhooks ready."

def start_flask():
    port = int(os.environ.get("PORT", 10000))
    web_app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)

# ========== DATA FUNCTIONS ==========
def load_data(filename):
    if os.path.exists(filename):
        with open(filename, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {} if filename != "questions.json" else []

def save_data(filename, data):
    with open(filename, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()

# ========== QUIZ QUESTIONS ==========
QUIZ_QUESTIONS = [
    {"id": "Q1", "text": "What is the capital of India?", "options": ["Mumbai", "New Delhi", "Kolkata", "Chennai"], "correct": "New Delhi"},
    {"id": "Q2", "text": "Who wrote the Indian national anthem?", "options": ["Bankim Chandra Chattopadhyay", "Rabindranath Tagore", "Sarojini Naidu", "Mahatma Gandhi"], "correct": "Rabindranath Tagore"},
    {"id": "Q3", "text": "Which planet is known as the Red Planet?", "options": ["Mars", "Jupiter", "Venus", "Saturn"], "correct": "Mars"}
]

# ========== KEYBOARD ==========
def get_keyboard(user_id=None):
    users = load_data("users.json")
    is_registered = user_id and str(user_id) in users
    has_paid = is_registered and users[str(user_id)].get("payment_completed", False)
    
    keyboard = [
        ["📝 Register", "👤 Profile"],
        ["🎯 Demo Quiz", "ℹ️ About"],
        ["💳 Pay ₹1", "💸 Set UPI"],
    ]
    if is_registered and has_paid:
        keyboard.append(["🔓 Start Quiz"])
    else:
        keyboard.append(["🔒 Start Quiz"])
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

# ========== TELEGRAM HANDLERS ==========
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    msg = f"""
🏆 *JANNAT FOUNDATION QUIZ* 🏆

Welcome {user.first_name}!

💰 *Win ₹1000!*

*How it works:*
1️⃣ Register
2️⃣ Pay ₹1 (TEST)
3️⃣ Answer 3 questions
4️⃣ Submit UPI
5️⃣ Get ₹1000 on Sunday!
"""
    await update.message.reply_text(msg, parse_mode="Markdown", reply_markup=get_keyboard(user.id))

async def register_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("📝 Send *Phone Number* with country code:\nExample: +919876543210", parse_mode="Markdown")
    return PHONE_REG

async def register_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["phone"] = update.message.text.strip()
    await update.message.reply_text("📝 Send *Password* (min 4 chars):", parse_mode="Markdown")
    return PASSWORD_REG

async def register_password(update: Update, context: ContextTypes.DEFAULT_TYPE):
    password = update.message.text.strip()
    user_id = update.effective_user.id
    if len(password) < 4:
        await update.message.reply_text("❌ Too short.")
        return PASSWORD_REG
    users = load_data("users.json")
    if str(user_id) in users:
        await update.message.reply_text("✅ Already registered!", reply_markup=get_keyboard(user_id))
        return ConversationHandler.END
    users[str(user_id)] = {
        "phone": context.user_data["phone"],
        "password": hash_password(password),
        "name": "", "place": "", "email": "", "upi_id": "",
        "payment_completed": False,
        "current_question_index": 0,
        "current_quiz_score": 0,
        "quiz_active": False,
        "registered_on": datetime.now().isoformat()
    }
    save_data("users.json", users)
    await update.message.reply_text("✅ *Registration Successful!*", parse_mode="Markdown", reply_markup=get_keyboard(user_id))
    return ConversationHandler.END

async def show_profile(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    users = load_data("users.json")
    if str(user_id) not in users:
        await update.message.reply_text("❌ Register first.", reply_markup=get_keyboard(user_id))
        return
    u = users[str(user_id)]
    text = f"""
👤 *Profile*

📱 Phone: {u.get('phone', 'Not set')}
👨 Name: {u.get('name', 'Not set')}
📍 Place: {u.get('place', 'Not set')}
📧 Email: {u.get('email', 'Not set')}
💸 UPI: {u.get('upi_id', 'Not set')}
💰 Paid: {'✅ Yes' if u.get('payment_completed') else '❌ No'}
🏆 Score: {u.get('current_quiz_score', 0)}/3
"""
    await update.message.reply_text(text, parse_mode="Markdown", reply_markup=get_keyboard(user_id))

async def update_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    name = update.message.text.replace("✏️ Name ", "").strip()
    users = load_data("users.json")
    if str(user_id) in users:
        users[str(user_id)]["name"] = name
        save_data("users.json", users)
        await update.message.reply_text("✅ Name updated!", reply_markup=get_keyboard(user_id))

async def update_place(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    place = update.message.text.replace("📍 Place ", "").strip()
    users = load_data("users.json")
    if str(user_id) in users:
        users[str(user_id)]["place"] = place
        save_data("users.json", users)
        await update.message.reply_text("✅ Place updated!", reply_markup=get_keyboard(user_id))

async def update_email(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    email = update.message.text.replace("📧 Email ", "").strip()
    users = load_data("users.json")
    if str(user_id) in users:
        users[str(user_id)]["email"] = email
        save_data("users.json", users)
        await update.message.reply_text("✅ Email updated!", reply_markup=get_keyboard(user_id))

async def demo_quiz(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    demo = {"question": "What is the capital of France?", "options": ["London", "Berlin", "Paris", "Madrid"], "correct": "Paris"}
    context.user_data["demo_q"] = demo
    context.user_data["awaiting_demo"] = True
    text = f"🎯 *DEMO QUIZ*\n\n{demo['question']}\n\n"
    for i, opt in enumerate(demo["options"]):
        text += f"{chr(65+i)}. {opt}\n"
    text += "\n*Reply with A, B, C, or D*"
    await update.message.reply_text(text, parse_mode="Markdown")

async def handle_demo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.user_data.get("awaiting_demo"):
        return
    user_id = update.effective_user.id
    answer = update.message.text.strip().upper()
    demo = context.user_data.get("demo_q", {})
    letters = {"A": 0, "B": 1, "C": 2, "D": 3}
    if answer in letters:
        selected = demo["options"][letters[answer]]
        if selected == demo.get("correct"):
            await update.message.reply_text("✅ Correct! Register and pay ₹1 to win ₹1000!", reply_markup=get_keyboard(user_id))
        else:
            await update.message.reply_text(f"❌ Wrong! Correct: {demo.get('correct')}", reply_markup=get_keyboard(user_id))
    else:
        await update.message.reply_text("Reply with A, B, C, or D", reply_markup=get_keyboard(user_id))
    context.user_data["awaiting_demo"] = False

async def payment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    users = load_data("users.json")
    if str(user_id) not in users:
        await update.message.reply_text("❌ Register first.", reply_markup=get_keyboard(user_id))
        return
    phone = users[str(user_id)].get("phone", "")
    try:
        payment_link = razorpay_client.payment_link.create({
            "amount": 100,
            "currency": "INR",
            "description": f"Jannat Quiz - User {user_id}",
            "customer": {"contact": phone} if phone else {},
            "notes": {"telegram_id": str(user_id)},
            "notify": {"sms": False, "email": False},
            "reminder_enable": False,
            "callback_url": "https://jannat-quiz-bot.onrender.com/payment-success",
            "callback_method": "get"
        })
        payment_url = payment_link["short_url"]
        await update.message.reply_text(
            f"💳 *PAY ₹1 (TEST)*\n\n🔗 [Click to pay]({payment_url})\n\n✅ *After payment, quiz unlocks automatically!*",
            parse_mode="Markdown",
            reply_markup=get_keyboard(user_id),
            disable_web_page_preview=False
        )
    except Exception as e:
        logger.error(f"Payment error: {e}")
        await update.message.reply_text(f"❌ Payment error", reply_markup=get_keyboard(user_id))

async def upi_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("💸 Send *UPI ID*:\nExample: username@okhdfcbank", parse_mode="Markdown")
    return UPI_INPUT

async def save_upi(update: Update, context: ContextTypes.DEFAULT_TYPE):
    upi = update.message.text.strip()
    user_id = update.effective_user.id
    users = load_data("users.json")
    if str(user_id) in users:
        users[str(user_id)]["upi_id"] = upi
        save_data("users.json", users)
        await update.message.reply_text("✅ UPI saved! Prize on Sunday.", reply_markup=get_keyboard(user_id))

async def start_quiz(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    users = load_data("users.json")
    if str(user_id) not in users:
        await update.message.reply_text("❌ Register first.", reply_markup=get_keyboard(user_id))
        return
    if not users[str(user_id)].get("payment_completed"):
        await update.message.reply_text("❌ Pay ₹1 first.", reply_markup=get_keyboard(user_id))
        return
    users[str(user_id)]["current_question_index"] = 0
    users[str(user_id)]["current_quiz_score"] = 0
    users[str(user_id)]["quiz_active"] = True
    save_data("users.json", users)
    context.user_data["quiz_active"] = True
    await send_question(update, context, user_id, 0)

async def send_question(update, context, user_id, index):
    if index >= len(QUIZ_QUESTIONS):
        users = load_data("users.json")
        score = users[str(user_id)].get("current_quiz_score", 0)
        users[str(user_id)]["quiz_active"] = False
        save_data("users.json", users)
        await update.message.reply_text(
            f"🎉 *Quiz Completed!* Score: {score}/3\n\nTap '💸 Set UPI' to claim ₹1000!",
            parse_mode="Markdown",
            reply_markup=get_keyboard(user_id)
        )
        context.user_data["quiz_active"] = False
        return
    q = QUIZ_QUESTIONS[index]
    context.user_data["current_q"] = q
    context.user_data["current_q_index"] = index
    text = f"🎯 *Q{index+1}/3*\n\n{q['text']}\n\n"
    for i, opt in enumerate(q["options"]):
        text += f"{chr(65+i)}. {opt}\n"
    text += "\n*Reply A, B, C, or D*"
    await update.message.reply_text(text, parse_mode="Markdown")

async def handle_quiz_answer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.user_data.get("quiz_active"):
        return
    user_id = update.effective_user.id
    answer = update.message.text.strip().upper()
    q = context.user_data.get("current_q", {})
    q_index = context.user_data.get("current_q_index", 0)
    letters = {"A": 0, "B": 1, "C": 2, "D": 3}
    if answer not in letters:
        await update.message.reply_text("Reply with A, B, C, or D")
        return
    selected = q["options"][letters[answer]]
    is_correct = (selected == q.get("correct"))
    users = load_data("users.json")
    if is_correct:
        users[str(user_id)]["current_quiz_score"] = users[str(user_id)].get("current_quiz_score", 0) + 1
        await update.message.reply_text("✅ Correct! +1 point", parse_mode="Markdown")
    else:
        await update.message.reply_text(f"❌ Wrong! Correct: {q.get('correct')}", parse_mode="Markdown")
    save_data("users.json", users)
    await send_question(update, context, user_id, q_index + 1)

async def about(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("📖 *Jannat Foundation Quiz*\n💰 Prize: ₹1000\n🎯 3 Questions\n📅 Payout: Sunday", parse_mode="Markdown", reply_markup=get_keyboard(update.effective_user.id))

async def locked_quiz(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🔒 *Quiz Locked*\n\nPay ₹1 using '💳 Pay ₹1' button.", parse_mode="Markdown", reply_markup=get_keyboard(update.effective_user.id))

async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("⛔ Not authorized.")
        return
    users = load_data("users.json")
    paid = sum(1 for u in users.values() if u.get("payment_completed"))
    await update.message.reply_text(f"📊 Stats\nUsers: {len(users)}\nPaid: {paid}")

async def verify_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("⛔ Not authorized.")
        return
    args = context.args
    if len(args) < 1:
        await update.message.reply_text("❌ Usage: /verify USER_ID")
        return
    user_id = args[0]
    users = load_data("users.json")
    if user_id not in users:
        await update.message.reply_text(f"❌ User {user_id} not found.")
        return
    users[user_id]["payment_completed"] = True
    save_data("users.json", users)
    await update.message.reply_text(f"✅ Verified user {user_id}!")
    try:
        await context.bot.send_message(int(user_id), "✅ *Payment Verified!* 🔓 Press '🔓 Start Quiz'!", parse_mode="Markdown")
    except:
        pass

# ========== MAIN ==========
def main():
    global telegram_app
    
    if not TOKEN:
        print("❌ No BOT_TOKEN!")
        return
    
    print("🤖 Bot starting...")
    
    # Initialize files
    if not os.path.exists("users.json"):
        save_data("users.json", {})
    
    # Start Flask in background
    Thread(target=start_flask, daemon=True).start()
    print("✅ Flask server started on port 10000")
    
    # Build Telegram app
    telegram_app = Application.builder().token(TOKEN).build()
    
    # Add all handlers
    reg_conv = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^📝 Register$"), register_start)],
        states={
            PHONE_REG: [MessageHandler(filters.TEXT & ~filters.COMMAND, register_phone)],
            PASSWORD_REG: [MessageHandler(filters.TEXT & ~filters.COMMAND, register_password)],
        },
        fallbacks=[]
    )
    telegram_app.add_handler(reg_conv)
    
    upi_conv = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^💸 Set UPI$"), upi_start)],
        states={UPI_INPUT: [MessageHandler(filters.TEXT & ~filters.COMMAND, save_upi)]},
        fallbacks=[]
    )
    telegram_app.add_handler(upi_conv)
    
    telegram_app.add_handler(MessageHandler(filters.Regex("^👤 Profile$"), show_profile))
    telegram_app.add_handler(MessageHandler(filters.Regex("^🎯 Demo Quiz$"), demo_quiz))
    telegram_app.add_handler(MessageHandler(filters.Regex("^ℹ️ About$"), about))
    telegram_app.add_handler(MessageHandler(filters.Regex("^💳 Pay ₹1$"), payment))
    telegram_app.add_handler(MessageHandler(filters.Regex("^🔓 Start Quiz$"), start_quiz))
    telegram_app.add_handler(MessageHandler(filters.Regex("^🔒 Start Quiz$"), locked_quiz))
    telegram_app.add_handler(MessageHandler(filters.Regex("^✏️ Name "), update_name))
    telegram_app.add_handler(MessageHandler(filters.Regex("^📍 Place "), update_place))
    telegram_app.add_handler(MessageHandler(filters.Regex("^📧 Email "), update_email))
    telegram_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_demo))
    telegram_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_quiz_answer))
    
    telegram_app.add_handler(CommandHandler("start", start))
    telegram_app.add_handler(CommandHandler("stats", stats))
    telegram_app.add_handler(CommandHandler("verify", verify_user))
    
    # Set webhook for Telegram (not polling!)
    webhook_url = "https://jannat-quiz-bot.onrender.com/webhook"
    
    async def setup_webhook():
        await telegram_app.bot.set_webhook(webhook_url)
        print(f"✅ Telegram webhook set to: {webhook_url}")
    
    # Run webhook setup
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(setup_webhook())
    
    print("✅ Bot ready with WEBHOOK mode!")
    print("📡 Webhook endpoints:")
    print("   - Telegram: https://jannat-quiz-bot.onrender.com/webhook")
    print("   - Razorpay: https://jannat-quiz-bot.onrender.com/razorpay-webhook")
    
    # Keep Flask running (already in thread)
    # Keep main thread alive
    import time
    while True:
        time.sleep(10)

if __name__ == "__main__":
    main()

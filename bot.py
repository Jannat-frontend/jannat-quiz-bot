import os
import json
import logging
import hashlib
import random
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

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# ========== RAZORPAY CLIENT ==========
razorpay_client = razorpay.Client(auth=(RAZORPAY_KEY_ID, RAZORPAY_KEY_SECRET))

# ========== FLASK WEBHOOK SERVER ==========
web_app = Flask(__name__)
telegram_app = None

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

# ========== WEBHOOK - HANDLES BOTH EVENT TYPES ==========
@web_app.route("/razorpay-webhook", methods=["POST"])
def razorpay_webhook():
    try:
        payload = request.get_json()
        logger.info(f"Webhook received")
        
        event = payload.get("event", "")
        
        if event not in ["payment_link.paid", "payment.captured"]:
            return jsonify({"status": "ignored"}), 200
        
        # Extract telegram_id from notes
        telegram_id = None
        amount = 0
        
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
        
        if not telegram_id:
            logger.warning("No telegram_id in payment notes")
            return jsonify({"error": "No telegram_id"}), 200
        
        # Mark user as paid
        users = load_data("users.json")
        if str(telegram_id) in users:
            users[str(telegram_id)]["payment_completed"] = True
            save_data("users.json", users)
            logger.info(f"✅ Payment confirmed for user {telegram_id}")
            
            if telegram_app:
                try:
                    confirmation_text = f"""✅ *Payment Confirmed!* 🎉

💰 Amount: ₹{amount}
🔓 Your quiz is now UNLOCKED!

Press the *'🔓 Start Quiz'* button below to play and win ₹1000!

You will get 3 questions. Answer correctly to win!"""
                    
                    telegram_app.create_task(
                        telegram_app.bot.send_message(
                            chat_id=int(telegram_id),
                            text=confirmation_text,
                            parse_mode="Markdown"
                        )
                    )
                except Exception as e:
                    logger.error(f"Failed to send confirmation: {e}")
        
        return jsonify({"status": "success"}), 200
        
    except Exception as e:
        logger.error(f"Webhook error: {e}")
        return jsonify({"error": str(e)}), 500

@web_app.route("/")
def home():
    return "Jannat Quiz Bot Webhook is running!"

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

# ========== KEYBOARD ==========
def get_keyboard(user_id=None):
    users = load_data("users.json")
    is_registered = user_id and str(user_id) in users
    has_paid = is_registered and users[str(user_id)].get("payment_completed", False)
    
    keyboard = [
        ["📝 Register", "👤 Profile"],
        ["🎯 Demo Quiz", "ℹ️ About"],
        ["💳 Pay ₹1 (Test)", "💸 Set UPI"],
    ]
    
    if is_registered and has_paid:
        keyboard.append(["🔓 Start Quiz"])
    else:
        keyboard.append(["🔒 Start Quiz"])
    
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

# ========== 3 QUIZ QUESTIONS ==========
QUIZ_QUESTIONS = [
    {
        "id": "Q1",
        "text": "What is the capital of India?",
        "options": ["Mumbai", "New Delhi", "Kolkata", "Chennai"],
        "correct": "New Delhi"
    },
    {
        "id": "Q2",
        "text": "Who wrote the Indian national anthem?",
        "options": ["Bankim Chandra Chattopadhyay", "Rabindranath Tagore", "Sarojini Naidu", "Mahatma Gandhi"],
        "correct": "Rabindranath Tagore"
    },
    {
        "id": "Q3",
        "text": "Which planet is known as the Red Planet?",
        "options": ["Mars", "Jupiter", "Venus", "Saturn"],
        "correct": "Mars"
    }
]

# ========== TELEGRAM BOT HANDLERS ==========
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    msg = f"""
🏆 *JANNAT FOUNDATION QUIZ* 🏆

Welcome {user.first_name}!

💰 *Win ₹1000!*

*How it works:*
1️⃣ Register with phone & password
2️⃣ Pay ₹1 (TEST MODE)
3️⃣ Answer 3 questions
4️⃣ Submit your UPI ID
5️⃣ Get ₹1000 on Sunday!

👇 *Tap buttons below* 👇
"""
    await update.message.reply_text(msg, parse_mode="Markdown", reply_markup=get_keyboard(user.id))

# ========== REGISTRATION ==========
async def register_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("📝 Send your *Phone Number* with country code:\nExample: +919876543210", parse_mode="Markdown")
    return PHONE_REG

async def register_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["phone"] = update.message.text.strip()
    await update.message.reply_text("📝 Send your *Password* (min 4 chars):", parse_mode="Markdown")
    return PASSWORD_REG

async def register_password(update: Update, context: ContextTypes.DEFAULT_TYPE):
    password = update.message.text.strip()
    user_id = update.effective_user.id
    
    if len(password) < 4:
        await update.message.reply_text("❌ Password too short. Try again.")
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

# ========== PROFILE ==========
async def show_profile(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    users = load_data("users.json")
    
    if str(user_id) not in users:
        await update.message.reply_text("❌ Register first.", reply_markup=get_keyboard(user_id))
        return
    
    u = users[str(user_id)]
    score = u.get("current_quiz_score", 0)
    text = f"""
👤 *Your Profile*

📱 Phone: {u.get('phone', 'Not set')}
👨 Name: {u.get('name', 'Not set')}
📍 Place: {u.get('place', 'Not set')}
📧 Email: {u.get('email', 'Not set')}
💸 UPI: {u.get('upi_id', 'Not set')}

💰 Paid: {'✅ Yes' if u.get('payment_completed') else '❌ No'}
🏆 Last Score: {score}/3
"""
    await update.message.reply_text(text, parse_mode="Markdown", reply_markup=get_keyboard(user_id))

# ========== UPDATE PROFILE ==========
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

# ========== DEMO QUIZ ==========
async def demo_quiz(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    demo = {
        "question": "What is the capital of France?",
        "options": ["London", "Berlin", "Paris", "Madrid"],
        "correct": "Paris"
    }
    context.user_data["demo_q"] = demo
    context.user_data["awaiting_demo"] = True
    
    text = f"🎯 *DEMO QUIZ (FREE)*\n\n{demo['question']}\n\n"
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

# ========== PAYMENT - DYNAMIC LINK ==========
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
            f"💳 *PAY ₹1 (TEST MODE)*\n\n"
            f"🔗 [Click here to pay ₹1]({payment_url})\n\n"
            f"✅ *After payment, your quiz will be UNLOCKED automatically!*\n\n"
            f"You will receive a confirmation message from the bot.\n\n"
            f"Then press '🔓 Start Quiz' to play 3 questions and win ₹1000!",
            parse_mode="Markdown",
            reply_markup=get_keyboard(user_id),
            disable_web_page_preview=False
        )
        
    except Exception as e:
        logger.error(f"Payment error: {e}")
        await update.message.reply_text("❌ Payment error. Please try again.", reply_markup=get_keyboard(user_id))

# ========== UPI ==========
async def upi_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("💸 Send your *UPI ID*:\nExample: username@okhdfcbank", parse_mode="Markdown")
    return UPI_INPUT

async def save_upi(update: Update, context: ContextTypes.DEFAULT_TYPE):
    upi = update.message.text.strip()
    user_id = update.effective_user.id
    users = load_data("users.json")
    
    if str(user_id) in users:
        users[str(user_id)]["upi_id"] = upi
        save_data("users.json", users)
        await update.message.reply_text("✅ UPI saved! Prize will be sent on Sunday.", reply_markup=get_keyboard(user_id))
        
        if ADMIN_ID:
            await context.bot.send_message(ADMIN_ID, f"💰 UPI submitted!\nUser: {user_id}\nUPI: {upi}")
    
    return ConversationHandler.END

# ========== START QUIZ - 3 QUESTIONS ==========
async def start_quiz(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    users = load_data("users.json")
    
    if str(user_id) not in users:
        await update.message.reply_text("❌ Register first.", reply_markup=get_keyboard(user_id))
        return
    
    if not users[str(user_id)].get("payment_completed"):
        await update.message.reply_text(
            "❌ *Payment Required*\n\nClick '💳 Pay ₹1 (Test)' to pay first.\n\nAfter payment, quiz will unlock automatically.",
            parse_mode="Markdown",
            reply_markup=get_keyboard(user_id)
        )
        return
    
    # Reset quiz progress
    users[str(user_id)]["current_question_index"] = 0
    users[str(user_id)]["current_quiz_score"] = 0
    users[str(user_id)]["quiz_active"] = True
    save_data("users.json", users)
    
    # Send first question
    await send_next_question(update, user_id)

async def send_next_question(update: Update, user_id):
    users = load_data("users.json")
    current_index = users[str(user_id)].get("current_question_index", 0)
    
    if current_index >= len(QUIZ_QUESTIONS):
        # Quiz completed
        score = users[str(user_id)].get("current_quiz_score", 0)
        users[str(user_id)]["quiz_active"] = False
        save_data("users.json", users)
        
        if score == 3:
            await update.message.reply_text(
                f"🎉 *PERFECT SCORE!* 🎉\n\nYou answered all {score}/3 questions correctly!\n\n🏆 Please click '💸 Set UPI' to receive your ₹1000 prize on Sunday!",
                parse_mode="Markdown",
                reply_markup=get_keyboard(user_id)
            )
        else:
            await update.message.reply_text(
                f"📊 *Quiz Completed!*\n\nYour score: {score}/3\n\n"
                f"{'✅ Great job!' if score >= 2 else '❌ Try again!'}\n\n"
                f"You can play again by paying ₹1.",
                parse_mode="Markdown",
                reply_markup=get_keyboard(user_id)
            )
        return
    
    # Send current question
    q = QUIZ_QUESTIONS[current_index]
    context = update.get_bot()
    
    text = f"🎯 *QUESTION {current_index + 1}/3*\n\n{q['text']}\n\n"
    for i, opt in enumerate(q["options"]):
        text += f"{chr(65+i)}. {opt}\n"
    text += "\n*Reply with A, B, C, or D*"
    
    await update.message.reply_text(text, parse_mode="Markdown")
    
    # Store current question in context
    context.chat_data["current_question"] = q
    context.chat_data["awaiting_quiz_answer"] = True

async def handle_quiz_answer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.chat_data.get("awaiting_quiz_answer"):
        return
    
    user_id = update.effective_user.id
    users = load_data("users.json")
    
    if not users.get(str(user_id), {}).get("quiz_active"):
        context.chat_data["awaiting_quiz_answer"] = False
        return
    
    answer = update.message.text.strip().upper()
    q = context.chat_data.get("current_question", {})
    
    letters = {"A": 0, "B": 1, "C": 2, "D": 3}
    
    if answer not in letters:
        await update.message.reply_text("Please reply with A, B, C, or D")
        return
    
    selected = q["options"][letters[answer]]
    is_correct = (selected == q.get("correct"))
    
    if is_correct:
        users[str(user_id)]["current_quiz_score"] = users[str(user_id)].get("current_quiz_score", 0) + 1
        await update.message.reply_text(f"✅ *Correct!* +1 point\n\n{q.get('correct')} is right!", parse_mode="Markdown")
    else:
        await update.message.reply_text(f"❌ *Wrong!*\n\nCorrect answer: {q.get('correct')}", parse_mode="Markdown")
    
    # Move to next question
    users[str(user_id)]["current_question_index"] = users[str(user_id)].get("current_question_index", 0) + 1
    save_data("users.json", users)
    
    context.chat_data["awaiting_quiz_answer"] = False
    
    # Send next question after delay
    import asyncio
    await asyncio.sleep(1.5)
    await send_next_question(update, user_id)

# ========== ABOUT ==========
async def about(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = """
📖 *Jannat Foundation Quiz*

💰 Prize: ₹1000
🎯 3 Questions
📅 Payout: Sunday

*How to win:*
• Register
• Pay ₹1 (Test Mode)
• Answer all 3 questions
• Submit UPI ID
• Get ₹1000 on Sunday!

*Contact:* @imtiazs37
"""
    await update.message.reply_text(text, parse_mode="Markdown", reply_markup=get_keyboard(update.effective_user.id))

async def locked_quiz(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🔒 *Quiz Locked*\n\nPay ₹1 first using '💳 Pay ₹1 (Test)' button.\n\nAfter payment, quiz will unlock automatically!",
        parse_mode="Markdown",
        reply_markup=get_keyboard(update.effective_user.id)
    )

# ========== ADMIN COMMANDS ==========
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
        await context.bot.send_message(
            int(user_id),
            "✅ *Payment Verified!* 🎉\n\n🔓 Press '🔓 Start Quiz' to play 3 questions and win ₹1000!",
            parse_mode="Markdown"
        )
    except:
        pass

async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("⛔ Not authorized.")
        return
    
    users = load_data("users.json")
    paid = sum(1 for u in users.values() if u.get("payment_completed"))
    total_score = sum(u.get("current_quiz_score", 0) for u in users.values())
    
    await update.message.reply_text(
        f"📊 *Statistics*\n\n👥 Users: {len(users)}\n💰 Paid: {paid}\n🏆 Total Score: {total_score}",
        parse_mode="Markdown"
    )

async def add_q(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("⛔ Not authorized.")
        return
    
    await update.message.reply_text("Questions are predefined. Edit QUIZ_QUESTIONS list in code to add more.")

# ========== MAIN ==========
def main():
    global telegram_app
    
    if not TOKEN:
        print("❌ No BOT_TOKEN!")
        return
    
    print("🤖 Bot starting with 3 questions...")
    print(f"👑 Admin ID: {ADMIN_ID}")
    
    # Init files
    for f in ["users.json"]:
        if not os.path.exists(f):
            save_data(f, {})
    
    # Start Flask in background
    Thread(target=start_flask, daemon=True).start()
    print("✅ Flask webhook server started")
    
    # Build Telegram app
    telegram_app = Application.builder().token(TOKEN).build()
    
    # Conversation handlers
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
    
    # Button handlers
    telegram_app.add_handler(MessageHandler(filters.Regex("^👤 Profile$"), show_profile))
    telegram_app.add_handler(MessageHandler(filters.Regex("^🎯 Demo Quiz$"), demo_quiz))
    telegram_app.add_handler(MessageHandler(filters.Regex("^ℹ️ About$"), about))
    telegram_app.add_handler(MessageHandler(filters.Regex("^💳 Pay ₹1 \\(Test\\)$"), payment))
    telegram_app.add_handler(MessageHandler(filters.Regex("^🔓 Start Quiz$"), start_quiz))
    telegram_app.add_handler(MessageHandler(filters.Regex("^🔒 Start Quiz$"), locked_quiz))
    
    # Answer handlers
    telegram_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_demo))
    telegram_app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_quiz_answer))
    
    # Profile update handlers
    telegram_app.add_handler(MessageHandler(filters.Regex("^✏️ Name "), update_name))
    telegram_app.add_handler(MessageHandler(filters.Regex("^📍 Place "), update_place))
    telegram_app.add_handler(MessageHandler(filters.Regex("^📧 Email "), update_email))
    
    # Commands
    telegram_app.add_handler(CommandHandler("start", start))
    telegram_app.add_handler(CommandHandler("verify", verify_user))
    telegram_app.add_handler(CommandHandler("stats", stats))
    telegram_app.add_handler(CommandHandler("addq", add_q))
    
    print("✅ Bot is ready! 3-question quiz with automatic payment verification.")
    print("📡 Webhook URL: https://jannat-quiz-bot.onrender.com/razorpay-webhook")
    telegram_app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()

import os
import json
import logging
import hashlib
import random
import requests
from datetime import datetime
from threading import Thread

from flask import Flask, request, jsonify
from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import Application, CommandHandler

import razorpay

# ========== CONFIGURATION ==========
TOKEN = os.environ.get("BOT_TOKEN")
RAZORPAY_KEY_ID = os.environ.get("RAZORPAY_KEY_ID")
RAZORPAY_KEY_SECRET = os.environ.get("RAZORPAY_KEY_SECRET")
ADMIN_ID = int(os.environ.get("ADMIN_ID", "0"))

# Logging
logging.basicConfig(
    format='%(asctime)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ========== RAZORPAY ==========
razorpay_client = razorpay.Client(auth=(RAZORPAY_KEY_ID, RAZORPAY_KEY_SECRET))

# ========== FLASK WEBHOOK ==========
web_app = Flask(__name__)

# ========== TELEGRAM WEBHOOK ROUTE ==========
@web_app.route("/webhook", methods=["POST"])
def telegram_webhook():
    """Receive updates from Telegram via webhook"""
    try:
        update_data = request.get_json()
        
        if update_data and 'message' in update_data:
            message = update_data['message']
            chat_id = message['chat']['id']
            text = message.get('text', '')
            
            logger.info(f"📱 Message from {chat_id}: {text}")
            
            # Handle commands
            if text == '/start':
                send_telegram_message(chat_id, get_start_message())
                send_keyboard(chat_id)
            elif text == "📝 Register":
                set_user_state(chat_id, "awaiting_phone")
                send_telegram_message(chat_id, "📝 Send your *Phone Number* with country code:\nExample: +919876543210", parse_mode="Markdown")
            elif text == "👤 Profile":
                show_profile(chat_id)
            elif text == "🎯 Demo Quiz":
                send_demo_quiz(chat_id)
            elif text == "ℹ️ About":
                send_telegram_message(chat_id, get_about_message(), parse_mode="Markdown")
            elif text == "💳 Pay ₹1":
                create_payment(chat_id)
            elif text == "💸 Set UPI":
                set_user_state(chat_id, "awaiting_upi")
                send_telegram_message(chat_id, "💸 Send your *UPI ID*:\nExample: username@okhdfcbank", parse_mode="Markdown")
            elif text in ["🔓 Start Quiz", "🔒 Start Quiz", "Start Quiz"]:
                # Handle both locked and unlocked button text
                start_quiz(chat_id)
            else:
                # Handle registration flow
                user_state = get_user_state(chat_id)
                if user_state == "awaiting_phone":
                    set_user_data(chat_id, "temp_phone", text)
                    set_user_state(chat_id, "awaiting_password")
                    send_telegram_message(chat_id, "📝 Send your *Password* (min 4 chars):", parse_mode="Markdown")
                elif user_state == "awaiting_password":
                    complete_registration(chat_id, text)
                elif user_state == "awaiting_upi":
                    save_upi(chat_id, text)
                elif user_state == "awaiting_demo":
                    handle_demo_answer(chat_id, text)
                elif user_state == "quiz_active":
                    handle_quiz_answer(chat_id, text)
                else:
                    send_telegram_message(chat_id, "Please use the buttons below.", reply_markup=get_keyboard(chat_id))
        
        return "OK", 200
    except Exception as e:
        logger.error(f"Webhook error: {e}")
        return "Error", 500

# ========== RAZORPAY WEBHOOK ROUTE ==========
@web_app.route("/razorpay-webhook", methods=["POST"])
def razorpay_webhook():
    """Handle Razorpay payment confirmation"""
    try:
        payload = request.get_json()
        logger.info(f"🔔 RAZORPAY WEBHOOK RECEIVED")
        
        event = payload.get("event", "")
        
        if event == "payment_link.paid":
            payment_link = payload.get("payload", {}).get("payment_link", {}).get("entity", {})
            notes = payment_link.get("notes", {})
            telegram_id = notes.get("telegram_id")
            amount = payment_link.get("amount", 0) / 100
            
            logger.info(f"💰 Payment Link paid: TG ID={telegram_id}, Amount=₹{amount}")
            
            if telegram_id:
                mark_user_paid(telegram_id, amount)
            
        elif event == "payment.captured":
            payment = payload.get("payload", {}).get("payment", {}).get("entity", {})
            notes = payment.get("notes", {})
            telegram_id = notes.get("telegram_id")
            amount = payment.get("amount", 0) / 100
            
            logger.info(f"💰 Payment captured: TG ID={telegram_id}, Amount=₹{amount}")
            
            if telegram_id:
                mark_user_paid(telegram_id, amount)
        
        return jsonify({"status": "success"}), 200
        
    except Exception as e:
        logger.error(f"Webhook error: {e}")
        return jsonify({"error": str(e)}), 500

def mark_user_paid(telegram_id, amount):
    """Mark user as paid and send confirmation with NEW KEYBOARD"""
    users = load_users()
    
    if str(telegram_id) not in users:
        logger.warning(f"User {telegram_id} not found")
        return
    
    users[str(telegram_id)]["payment_completed"] = True
    save_users(users)
    
    logger.info(f"✅ User {telegram_id} marked as paid")
    
    # Send confirmation with updated keyboard (UNLOCKED)
    keyboard = {
        "keyboard": [
            ["📝 Register", "👤 Profile"],
            ["🎯 Demo Quiz", "ℹ️ About"],
            ["💳 Pay ₹1", "💸 Set UPI"],
            ["🔓 Start Quiz"]
        ],
        "resize_keyboard": True
    }
    
    send_telegram_message(
        int(telegram_id),
        f"✅ *Payment Confirmed!* 🎉\n\n💰 Amount: ₹{amount}\n\n🔓 *Quiz UNLOCKED!*\n\nPress '🔓 Start Quiz' to play 3 questions and win ₹1000!",
        parse_mode="Markdown",
        reply_markup=keyboard
    )

# ========== PAYMENT SUCCESS PAGE ==========
@web_app.route("/payment-success", methods=["GET"])
def payment_success():
    return """
    <!DOCTYPE html>
    <html>
    <head><title>Payment Received</title></head>
    <body style="font-family: Arial; text-align: center; padding: 50px;">
        <h1>✅ Donation Received!</h1>
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
    return jsonify({"status": "alive"})

@web_app.route("/")
def home():
    return "Jannat Quiz Bot is running!"

def start_flask():
    port = int(os.environ.get("PORT", 10000))
    web_app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)

# ========== HELPER FUNCTIONS ==========
def send_telegram_message(chat_id, text, reply_markup=None, parse_mode="Markdown"):
    """Send message via Telegram API"""
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    data = {"chat_id": chat_id, "text": text, "parse_mode": parse_mode}
    if reply_markup:
        data["reply_markup"] = reply_markup
    try:
        response = requests.post(url, json=data)
        logger.info(f"Message sent to {chat_id}: {response.status_code}")
        return response.json()
    except Exception as e:
        logger.error(f"Failed to send message: {e}")
        return None

def send_keyboard(chat_id):
    """Send initial keyboard to user"""
    keyboard = {
        "keyboard": [
            ["📝 Register", "👤 Profile"],
            ["🎯 Demo Quiz", "ℹ️ About"],
            ["💳 Pay ₹1", "💸 Set UPI"],
            ["🔒 Start Quiz"]
        ],
        "resize_keyboard": True
    }
    send_telegram_message(chat_id, "Use the buttons below:", reply_markup=keyboard)

def get_keyboard(chat_id):
    """Get appropriate keyboard based on user's payment status"""
    users = load_users()
    is_registered = str(chat_id) in users and users[str(chat_id)].get("registered", False)
    has_paid = is_registered and users[str(chat_id)].get("payment_completed", False)
    
    keyboard = [
        ["📝 Register", "👤 Profile"],
        ["🎯 Demo Quiz", "ℹ️ About"],
        ["💳 Pay ₹1", "💸 Set UPI"],
    ]
    
    if is_registered and has_paid:
        keyboard.append(["🔓 Start Quiz"])
    else:
        keyboard.append(["🔒 Start Quiz"])
    
    return {"keyboard": keyboard, "resize_keyboard": True}

def get_start_message():
    return """
🏆 *JANNAT FOUNDATION QUIZ* 🏆

💰 *Win ₹1000!*

*How it works:*
1️⃣ Register
2️⃣ Donate ₹1
3️⃣ Answer 3 questions
4️⃣ Submit UPI
5️⃣ Get ₹1000 on Sunday!
"""

def get_about_message():
    return """
📖 *Jannat Foundation Quiz*

💰 Prize: ₹1000
🎯 3 Questions
📅 Payout: Sunday

*Contact:* @imtiazs37
"""

# ========== DATA FUNCTIONS ==========
def load_users():
    if os.path.exists("users.json"):
        with open("users.json", 'r', encoding='utf-8') as f:
            return json.load(f)
    return {}

def save_users(users):
    with open("users.json", 'w', encoding='utf-8') as f:
        json.dump(users, f, indent=2, ensure_ascii=False)

def get_user_state(chat_id):
    users = load_users()
    return users.get(str(chat_id), {}).get("state", None)

def set_user_state(chat_id, state):
    users = load_users()
    if str(chat_id) not in users:
        users[str(chat_id)] = {}
    users[str(chat_id)]["state"] = state
    save_users(users)

def get_user_data(chat_id, key):
    users = load_users()
    return users.get(str(chat_id), {}).get(key, None)

def set_user_data(chat_id, key, value):
    users = load_users()
    if str(chat_id) not in users:
        users[str(chat_id)] = {}
    users[str(chat_id)][key] = value
    save_users(users)

def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()

# ========== PROFILE ==========
def show_profile(chat_id):
    users = load_users()
    if str(chat_id) not in users:
        send_telegram_message(chat_id, "❌ Register first.", reply_markup=get_keyboard(chat_id))
        return
    
    u = users[str(chat_id)]
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
    send_telegram_message(chat_id, text, parse_mode="Markdown", reply_markup=get_keyboard(chat_id))

# ========== REGISTRATION ==========
def complete_registration(chat_id, password):
    if len(password) < 4:
        send_telegram_message(chat_id, "❌ Password too short. Try again.")
        return
    
    users = load_users()
    phone = get_user_data(chat_id, "temp_phone")
    
    if str(chat_id) in users:
        send_telegram_message(chat_id, "✅ Already registered!", reply_markup=get_keyboard(chat_id))
        return
    
    users[str(chat_id)] = {
        "phone": phone,
        "password": hash_password(password),
        "name": "", "place": "", "email": "", "upi_id": "",
        "payment_completed": False,
        "current_question_index": 0,
        "current_quiz_score": 0,
        "quiz_active": False,
        "registered": True,
        "registered_on": datetime.now().isoformat()
    }
    save_users(users)
    set_user_state(chat_id, None)
    
    send_telegram_message(chat_id, "✅ *Registration Successful!*", parse_mode="Markdown", reply_markup=get_keyboard(chat_id))

# ========== UPI ==========
def save_upi(chat_id, upi_id):
    users = load_users()
    if str(chat_id) in users:
        users[str(chat_id)]["upi_id"] = upi_id
        save_users(users)
        set_user_state(chat_id, None)
        send_telegram_message(chat_id, "✅ UPI saved! Prize on Sunday.", reply_markup=get_keyboard(chat_id))

# ========== DEMO QUIZ ==========
def send_demo_quiz(chat_id):
    demo = {"question": "What is the capital of France?", "options": ["London", "Berlin", "Paris", "Madrid"], "correct": "Paris"}
    set_user_data(chat_id, "demo_q", demo)
    set_user_state(chat_id, "awaiting_demo")
    
    text = f"🎯 *DEMO QUIZ*\n\n{demo['question']}\n\nA. London\nB. Berlin\nC. Paris\nD. Madrid\n\n*Reply with A, B, C, or D*"
    send_telegram_message(chat_id, text, parse_mode="Markdown")

def handle_demo_answer(chat_id, answer):
    demo = get_user_data(chat_id, "demo_q")
    if not demo:
        set_user_state(chat_id, None)
        return
    
    letter_map = {"A": 0, "B": 1, "C": 2, "D": 3}
    
    if answer in letter_map:
        selected = demo["options"][letter_map[answer]]
        if selected == demo.get("correct"):
            send_telegram_message(chat_id, "✅ Correct! Register and pay ₹1 to win ₹1000!", reply_markup=get_keyboard(chat_id))
        else:
            send_telegram_message(chat_id, f"❌ Wrong! Correct: {demo.get('correct')}", reply_markup=get_keyboard(chat_id))
    else:
        send_telegram_message(chat_id, "Please reply with A, B, C, or D")
    
    set_user_state(chat_id, None)

# ========== PAYMENT ==========
def create_payment(chat_id):
    """Create Razorpay payment link"""
    users = load_users()
    if str(chat_id) not in users:
        send_telegram_message(chat_id, "❌ Register first.", reply_markup=get_keyboard(chat_id))
        return
    
    logger.info(f"💳 Creating payment for user {chat_id}")
    
    try:
        payment_link_data = {
            "amount": 100,
            "currency": "INR",
            "description": f"Jannat Quiz - User {chat_id}",
            "notes": {"telegram_id": str(chat_id)},
            "callback_url": "https://jannat-quiz-bot.onrender.com/payment-success",
            "callback_method": "get"
        }
        
        payment_link = razorpay_client.payment_link.create(payment_link_data)
        payment_url = payment_link["short_url"]
        
        logger.info(f"✅ Payment link created: {payment_url}")
        
        send_telegram_message(
            chat_id,
            f"💳 *PAY ₹1 (TEST)*\n\n🔗 [Click here to pay ₹1]({payment_url})\n\n✅ *After Donation, quiz unlocks automatically!*",
            parse_mode="Markdown",
            reply_markup=get_keyboard(chat_id)
        )
        
    except Exception as e:
        error_msg = str(e)
        logger.error(f"❌ Payment error: {error_msg}")
        send_telegram_message(
            chat_id, 
            f"❌ Payment Error\n\n{error_msg[:200]}",
            reply_markup=get_keyboard(chat_id)
        )

# ========== QUIZ ==========
QUIZ_QUESTIONS = [
    {"id": "Q1", "text": "What is the capital of India?", "options": ["Mumbai", "New Delhi", "Kolkata", "Chennai"], "correct": "New Delhi"},
    {"id": "Q2", "text": "Who wrote the Indian national anthem?", "options": ["Bankim Chandra Chattopadhyay", "Rabindranath Tagore", "Sarojini Naidu", "Mahatma Gandhi"], "correct": "Rabindranath Tagore"},
    {"id": "Q3", "text": "Which planet is known as the Red Planet?", "options": ["Mars", "Jupiter", "Venus", "Saturn"], "correct": "Mars"}
]

def start_quiz(chat_id):
    """Start the quiz - checks payment status first"""
    users = load_users()
    
    if str(chat_id) not in users:
        send_telegram_message(chat_id, "❌ Register first.", reply_markup=get_keyboard(chat_id))
        return
    
    user = users[str(chat_id)]
    
    # Check if payment is completed
    if not user.get("payment_completed"):
        logger.warning(f"User {chat_id} attempted quiz without payment. payment_completed={user.get('payment_completed')}")
        send_telegram_message(
            chat_id, 
            "❌ *Quiz Locked*\n\nYou need to pay ₹1 first.\n\nClick '💳 Pay ₹1' to continue.",
            parse_mode="Markdown",
            reply_markup=get_keyboard(chat_id)
        )
        return
    
    # Donation verified - start quiz
    logger.info(f"✅ Starting quiz for user {chat_id}")
    
    users[str(chat_id)]["current_question_index"] = 0
    users[str(chat_id)]["current_quiz_score"] = 0
    users[str(chat_id)]["quiz_active"] = True
    save_users(users)
    set_user_state(chat_id, "quiz_active")
    
    send_question(chat_id, 0)

def send_question(chat_id, index):
    """Send a quiz question"""
    if index >= len(QUIZ_QUESTIONS):
        users = load_users()
        score = users[str(chat_id)].get("current_quiz_score", 0)
        users[str(chat_id)]["quiz_active"] = False
        save_users(users)
        set_user_state(chat_id, None)
        
        send_telegram_message(
            chat_id,
            f"🎉 *Quiz Completed!* 🎉\n\nYour score: {score}/3\n\nTap '💸 Set UPI' to claim ₹1000!",
            parse_mode="Markdown",
            reply_markup=get_keyboard(chat_id)
        )
        return
    
    q = QUIZ_QUESTIONS[index]
    set_user_data(chat_id, "current_q", q)
    set_user_data(chat_id, "current_q_index", index)
    
    text = f"🎯 *Question {index+1}/3*\n\n{q['text']}\n\nA. {q['options'][0]}\nB. {q['options'][1]}\nC. {q['options'][2]}\nD. {q['options'][3]}\n\n*Reply with A, B, C, or D*"
    send_telegram_message(chat_id, text, parse_mode="Markdown")

def handle_quiz_answer(chat_id, answer):
    """Handle quiz answer"""
    users = load_users()
    
    if not users.get(str(chat_id), {}).get("quiz_active"):
        return
    
    q = get_user_data(chat_id, "current_q")
    q_index = get_user_data(chat_id, "current_q_index")
    
    if not q:
        set_user_state(chat_id, None)
        return
    
    letter_map = {"A": 0, "B": 1, "C": 2, "D": 3}
    
    if answer not in letter_map:
        send_telegram_message(chat_id, "Please reply with A, B, C, or D")
        return
    
    selected = q["options"][letter_map[answer]]
    is_correct = (selected == q.get("correct"))
    
    if is_correct:
        users[str(chat_id)]["current_quiz_score"] = users[str(chat_id)].get("current_quiz_score", 0) + 1
        send_telegram_message(chat_id, "✅ *Correct!* +1 point", parse_mode="Markdown")
    else:
        send_telegram_message(chat_id, f"❌ *Wrong!*\n\nCorrect answer: {q.get('correct')}", parse_mode="Markdown")
    
    save_users(users)
    send_question(chat_id, q_index + 1)

# ========== ADMIN COMMANDS ==========
async def admin_stats(update, context):
    chat_id = update.effective_user.id
    if chat_id != ADMIN_ID:
        await update.message.reply_text("⛔ Not authorized.")
        return
    users = load_users()
    paid = sum(1 for u in users.values() if u.get("payment_completed"))
    await update.message.reply_text(f"📊 Stats\nUsers: {len(users)}\nPaid: {paid}")

async def admin_verify(update, context):
    chat_id = update.effective_user.id
    if chat_id != ADMIN_ID:
        await update.message.reply_text("⛔ Not authorized.")
        return
    args = context.args
    if len(args) < 1:
        await update.message.reply_text("❌ Usage: /verify USER_ID")
        return
    user_id = args[0]
    users = load_users()
    if user_id not in users:
        await update.message.reply_text(f"❌ User {user_id} not found.")
        return
    users[user_id]["payment_completed"] = True
    save_users(users)
    await update.message.reply_text(f"✅ Verified user {user_id}!")
    mark_user_paid(int(user_id), 1.0)

# ========== MAIN ==========
def main():
    if not TOKEN:
        print("❌ No BOT_TOKEN!")
        return
    
    print("🤖 Bot starting...")
    
    # Initialize files
    if not os.path.exists("users.json"):
        save_users({})
    
    # Start Flask
    Thread(target=start_flask, daemon=True).start()
    print("✅ Flask server started")
    
    # Build Telegram app for admin commands
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("stats", admin_stats))
    app.add_handler(CommandHandler("verify", admin_verify))
    
    # Set webhook
    webhook_url = "https://jannat-quiz-bot.onrender.com/webhook"
    import asyncio
    async def set_webhook():
        await app.bot.set_webhook(webhook_url)
        print(f"✅ Webhook set to: {webhook_url}")
    
    asyncio.run(set_webhook())
    
    print("✅ Bot ready!")
    print("📡 Endpoints:")
    print("   - Telegram webhook: https://jannat-quiz-bot.onrender.com/webhook")
    print("   - Razorpay webhook: https://jannat-quiz-bot.onrender.com/razorpay-webhook")
    
    # Keep main thread alive
    import time
    while True:
        time.sleep(10)

if __name__ == "__main__":
    main()

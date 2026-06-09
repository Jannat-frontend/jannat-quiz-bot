import os
import json
import logging
import hashlib
import random
import requests
from datetime import datetime
from threading import Thread

from flask import Flask, request, jsonify
from telegram import Update
from telegram.ext import Application, CommandHandler

import razorpay

# ========== CONFIGURATION ==========
TOKEN = os.environ.get("BOT_TOKEN")
RAZORPAY_KEY_ID = os.environ.get("RAZORPAY_KEY_ID")
RAZORPAY_KEY_SECRET = os.environ.get("RAZORPAY_KEY_SECRET")
ADMIN_ID = int(os.environ.get("ADMIN_ID", "0"))

# Quiz settings
QUESTIONS_PER_QUIZ = 2
DONATION_AMOUNT = 100  # 100 paise = ₹1

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

# Store bot application for webhook processing
telegram_application = None

# ========== TELEGRAM WEBHOOK ROUTE ==========
@web_app.route("/webhook", methods=["POST", "GET"])
def telegram_webhook():
    """Receive updates from Telegram via webhook"""
    if request.method == "GET":
        return jsonify({"status": "alive", "message": "Webhook endpoint is working"}), 200
    
    try:
        update_data = request.get_json()
        logger.info(f"📨 Telegram webhook received")
        
        if update_data and telegram_application:
            # Process the update
            update = Update.de_json(update_data, telegram_application.bot)
            telegram_application.update_queue.put_nowait(update)
            logger.info(f"✅ Update queued for processing")
        
        return "OK", 200
    except Exception as e:
        logger.error(f"Telegram webhook error: {e}")
        return "Error", 500

# ========== RAZORPAY WEBHOOK ROUTE ==========
@web_app.route("/razorpay-webhook", methods=["POST", "GET"])
def razorpay_webhook():
    """Handle Razorpay payment confirmation"""
    if request.method == "GET":
        return jsonify({"status": "alive", "message": "Razorpay webhook endpoint is working"}), 200
    
    try:
        payload = request.get_json()
        logger.info(f"🔔 RAZORPAY WEBHOOK RECEIVED")
        
        event = payload.get("event", "")
        
        if event == "payment_link.paid":
            payment_link = payload.get("payload", {}).get("payment_link", {}).get("entity", {})
            notes = payment_link.get("notes", {})
            telegram_id = notes.get("telegram_id")
            amount = payment_link.get("amount", 0) / 100
            
            logger.info(f"💰 Donation received: TG ID={telegram_id}, Amount=₹{amount}")
            
            if telegram_id:
                mark_user_donated(telegram_id, amount)
            
        elif event == "payment.captured":
            payment = payload.get("payload", {}).get("payment", {}).get("entity", {})
            notes = payment.get("notes", {})
            telegram_id = notes.get("telegram_id")
            amount = payment.get("amount", 0) / 100
            
            logger.info(f"💰 Donation captured: TG ID={telegram_id}, Amount=₹{amount}")
            
            if telegram_id:
                mark_user_donated(telegram_id, amount)
        
        return jsonify({"status": "success"}), 200
        
    except Exception as e:
        logger.error(f"Webhook error: {e}")
        return jsonify({"error": str(e)}), 500

def mark_user_donated(telegram_id, amount):
    """Mark user as donated and unlock quiz"""
    users = load_users()
    
    if str(telegram_id) not in users:
        logger.warning(f"User {telegram_id} not found")
        return
    
    # Update donation stats
    users[str(telegram_id)]["donation_completed"] = True
    users[str(telegram_id)]["total_donations"] = users[str(telegram_id)].get("total_donations", 0) + 1
    users[str(telegram_id)]["last_donation_date"] = datetime.now().isoformat()
    save_users(users)
    
    logger.info(f"✅ User {telegram_id} marked as donated (Total: {users[str(telegram_id)]['total_donations']})")
    
    # Send confirmation with updated keyboard
    keyboard = {
        "keyboard": [
            ["📝 Register", "👤 Profile"],
            ["🎯 Demo Quiz", "ℹ️ About"],
            ["💳 Donate ₹1", "💸 Set UPI"],
            ["🔓 Start Quiz"]
        ],
        "resize_keyboard": True
    }
    
    send_telegram_message(
        int(telegram_id),
        f"✅ *Donation Received!* 🎉\n\n💰 Amount: ₹{amount}\n🙏 JazakAllah Khair for your donation!\n\n🔓 *Quiz UNLOCKED!*\n\nPress '🔓 Start Quiz' to play and win ₹1000!",
        parse_mode="Markdown",
        reply_markup=keyboard
    )

# ========== PAYMENT SUCCESS PAGE ==========
@web_app.route("/donation-success", methods=["GET"])
def donation_success():
    return """
    <!DOCTYPE html>
    <html>
    <head><title>Donation Received</title></head>
    <body style="font-family: Arial; text-align: center; padding: 50px;">
        <h1>✅ Donation Received!</h1>
        <h2>Your quiz is being unlocked...</h2>
        <p>Please return to Telegram and press <strong>Start Quiz</strong>.</p>
        <p>JazakAllah Khair for your support!</p>
        <hr>
        <p>Jannat Foundation Trust</p>
    </body>
    </html>
    """

@web_app.route("/")
def home():
    return "Jannat Foundation Quiz Bot is running!"

def start_flask():
    port = int(os.environ.get("PORT", 10000))
    web_app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)

# ========== HELPER FUNCTIONS ==========
def send_telegram_message(chat_id, text, reply_markup=None, parse_mode="Markdown"):
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    data = {"chat_id": chat_id, "text": text, "parse_mode": parse_mode}
    if reply_markup:
        data["reply_markup"] = reply_markup
    try:
        response = requests.post(url, json=data)
        return response.json()
    except Exception as e:
        logger.error(f"Failed to send message: {e}")
        return None

def send_keyboard(chat_id):
    keyboard = {
        "keyboard": [
            ["📝 Register", "👤 Profile"],
            ["🎯 Demo Quiz", "ℹ️ About"],
            ["💳 Donate ₹1", "💸 Set UPI"],
            ["🔒 Start Quiz"]
        ],
        "resize_keyboard": True
    }
    send_telegram_message(chat_id, "Use the buttons below:", reply_markup=keyboard)

def get_keyboard(chat_id):
    users = load_users()
    is_registered = str(chat_id) in users and users[str(chat_id)].get("registered", False)
    has_donated = is_registered and users[str(chat_id)].get("donation_completed", False)
    
    keyboard = [
        ["📝 Register", "👤 Profile"],
        ["🎯 Demo Quiz", "ℹ️ About"],
        ["💳 Donate ₹1", "💸 Set UPI"],
    ]
    
    if is_registered and has_donated:
        keyboard.append(["🔓 Start Quiz"])
    else:
        keyboard.append(["🔒 Start Quiz"])
    
    return {"keyboard": keyboard, "resize_keyboard": True}

def get_start_message():
    return """
🏆 *JANNAT FOUNDATION QUIZ* 🏆

*Helping the Needy & Calamity Hit People*

💰 *Win ₹1000 Prize!*

*How it works:*
1️⃣ Register with phone & password
2️⃣ Donate ₹1 (Test Mode)
3️⃣ Answer 2 questions correctly
4️⃣ Submit your UPI ID
5️⃣ Get ₹1000 on Sunday!

🙏 *Your donation helps support disabled and calamity-hit people.*

👇 *Use the buttons below* 👇
"""

def get_about_message():
    return """
📖 *Jannat Foundation Trust*

*Mission:* Helping disabled and calamity-hit people.

💰 *Quiz Prize:* ₹1000
🎯 *Questions:* 2 per quiz
📅 *Payout:* Every Sunday

*Rules:*
• Register once
• Donate ₹1 per quiz attempt
• Answer both questions correctly
• Submit UPI ID to claim prize
• No question repeats for same user

*Contact:* @imtiazs37

*Jannat Foundation Trust*
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

def load_questions():
    if os.path.exists("questions.json"):
        with open("questions.json", 'r', encoding='utf-8') as f:
            return json.load(f)
    # Default questions
    return [
        {"id": 1, "text": "What is the capital of India?", "options": ["Mumbai", "New Delhi", "Kolkata", "Chennai"], "correct": "New Delhi"},
        {"id": 2, "text": "Who wrote the Indian national anthem?", "options": ["Bankim Chandra Chattopadhyay", "Rabindranath Tagore", "Sarojini Naidu", "Mahatma Gandhi"], "correct": "Rabindranath Tagore"},
        {"id": 3, "text": "Which planet is known as the Red Planet?", "options": ["Mars", "Jupiter", "Venus", "Saturn"], "correct": "Mars"},
        {"id": 4, "text": "What is the national animal of India?", "options": ["Lion", "Tiger", "Elephant", "Peacock"], "correct": "Tiger"},
        {"id": 5, "text": "Who is known as the Father of the Nation in India?", "options": ["Jawaharlal Nehru", "Mahatma Gandhi", "Subhas Chandra Bose", "Sardar Patel"], "correct": "Mahatma Gandhi"},
    ]

def save_questions(questions):
    with open("questions.json", 'w', encoding='utf-8') as f:
        json.dump(questions, f, indent=2, ensure_ascii=False)

def load_winners():
    if os.path.exists("winners.json"):
        with open("winners.json", 'r', encoding='utf-8') as f:
            return json.load(f)
    return []

def save_winners(winners):
    with open("winners.json", 'w', encoding='utf-8') as f:
        json.dump(winners, f, indent=2, ensure_ascii=False)

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
👤 *Your Profile*

📱 Phone: {u.get('phone', 'Not set')}
👨 Name: {u.get('name', 'Not set')}
📍 Place: {u.get('place', 'Not set')}
📧 Email: {u.get('email', 'Not set')}
💸 UPI: {u.get('upi_id', 'Not set')}

💰 Total Donations: ₹{u.get('total_donations', 0)}
🎯 Total Attempts: {u.get('total_attempts', 0)}
🏆 Wins: {u.get('wins', 0)}
✅ Donated for Current Quiz: {'Yes' if u.get('donation_completed') else 'No'}

*JazakAllah Khair for your support!*
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
        "donation_completed": False,
        "total_donations": 0,
        "total_attempts": 0,
        "wins": 0,
        "answered_questions": [],
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
        send_telegram_message(chat_id, "✅ UPI saved! Prize will be sent on Sunday.", reply_markup=get_keyboard(chat_id))

# ========== DEMO QUIZ ==========
def send_demo_quiz(chat_id):
    demo = {"question": "What is the capital of France?", "options": ["London", "Berlin", "Paris", "Madrid"], "correct": "Paris"}
    set_user_data(chat_id, "demo_q", demo)
    set_user_state(chat_id, "awaiting_demo")
    
    text = f"🎯 *DEMO QUIZ (FREE)*\n\n{demo['question']}\n\nA. London\nB. Berlin\nC. Paris\nD. Madrid\n\n*Reply with A, B, C, or D*"
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
            send_telegram_message(chat_id, "✅ Correct! Register and donate ₹1 to win ₹1000!", reply_markup=get_keyboard(chat_id))
        else:
            send_telegram_message(chat_id, f"❌ Wrong! Correct: {demo.get('correct')}\n\n📝 Register and donate ₹1 to play the real quiz!", reply_markup=get_keyboard(chat_id))
    else:
        send_telegram_message(chat_id, "Please reply with A, B, C, or D")
    
    set_user_state(chat_id, None)

# ========== DONATION ==========
def create_donation(chat_id):
    users = load_users()
    if str(chat_id) not in users:
        send_telegram_message(chat_id, "❌ Register first.", reply_markup=get_keyboard(chat_id))
        return
    
    logger.info(f"💳 Creating donation for user {chat_id}")
    
    try:
        payment_link_data = {
            "amount": DONATION_AMOUNT,
            "currency": "INR",
            "description": f"Jannat Foundation Quiz Donation - User {chat_id}",
            "notes": {"telegram_id": str(chat_id)},
            "callback_url": "https://jannat-quiz-bot.onrender.com/donation-success",
            "callback_method": "get"
        }
        
        payment_link = razorpay_client.payment_link.create(payment_link_data)
        payment_url = payment_link["short_url"]
        
        send_telegram_message(
            chat_id,
            f"💳 *DONATE ₹{DONATION_AMOUNT//100}* 🙏\n\n🔗 [Click here to donate]({payment_url})\n\n✅ *After donation, quiz unlocks automatically!*\n\n🙏 Your donation helps disabled and calamity-hit people.",
            parse_mode="Markdown",
            reply_markup=get_keyboard(chat_id)
        )
        
    except Exception as e:
        error_msg = str(e)
        logger.error(f"❌ Donation error: {error_msg}")
        send_telegram_message(chat_id, f"❌ Donation Error\n\n{error_msg[:200]}", reply_markup=get_keyboard(chat_id))

# ========== QUIZ ==========
def start_quiz(chat_id):
    users = load_users()
    
    if str(chat_id) not in users:
        send_telegram_message(chat_id, "❌ Register first.", reply_markup=get_keyboard(chat_id))
        return
    
    user = users[str(chat_id)]
    
    if not user.get("donation_completed"):
        send_telegram_message(
            chat_id, 
            "❌ *Quiz Locked*\n\nYou need to donate ₹1 first.\n\nClick '💳 Donate ₹1' to continue.\n\n🙏 Your donation helps disabled and calamity-hit people.",
            parse_mode="Markdown",
            reply_markup=get_keyboard(chat_id)
        )
        return
    
    # Reset donation flag for this quiz attempt
    users[str(chat_id)]["donation_completed"] = False
    users[str(chat_id)]["total_attempts"] = user.get("total_attempts", 0) + 1
    users[str(chat_id)]["current_quiz_score"] = 0
    users[str(chat_id)]["quiz_active"] = True
    save_users(users)
    
    # Get questions that user hasn't seen before
    all_questions = load_questions()
    answered_questions = user.get("answered_questions", [])
    available_questions = [q for q in all_questions if q["id"] not in answered_questions]
    
    if len(available_questions) < QUESTIONS_PER_QUIZ:
        send_telegram_message(
            chat_id,
            "📚 *No more new questions!*\n\nYou have attempted all available questions.\nMore questions will be added soon.\n\nJazakAllah Khair for your participation!",
            parse_mode="Markdown",
            reply_markup=get_keyboard(chat_id)
        )
        users[str(chat_id)]["quiz_active"] = False
        save_users(users)
        return
    
    # Select random questions
    selected_questions = random.sample(available_questions, QUESTIONS_PER_QUIZ)
    users[str(chat_id)]["current_questions"] = selected_questions
    users[str(chat_id)]["current_question_index"] = 0
    save_users(users)
    set_user_state(chat_id, "quiz_active")
    
    send_question(chat_id, 0)

def send_question(chat_id, index):
    users = load_users()
    questions = users[str(chat_id)].get("current_questions", [])
    
    if index >= len(questions):
        # Quiz completed - check score
        score = users[str(chat_id)].get("current_quiz_score", 0)
        
        if score == QUESTIONS_PER_QUIZ:
            # Winner!
            users[str(chat_id)]["wins"] = users[str(chat_id)].get("wins", 0) + 1
            save_users(users)
            
            # Add to winners list
            winners = load_winners()
            winner_entry = {
                "telegram_id": chat_id,
                "name": users[str(chat_id)].get("name", "Unknown"),
                "phone": users[str(chat_id)].get("phone", "Unknown"),
                "upi": users[str(chat_id)].get("upi_id", "Not set"),
                "score": score,
                "date": datetime.now().isoformat(),
                "status": "Pending"
            }
            winners.append(winner_entry)
            save_winners(winners)
            
            send_telegram_message(
                chat_id,
                f"🎉 *CONGRATULATIONS!* 🎉\n\n✅ Score: {score}/{QUESTIONS_PER_QUIZ}\n🎉 You are eligible for the prize!\n\n📄 *Please click '💸 Set UPI' to update your UPI ID.*\n\n🏆 *Jannat Foundation will pay your prize to this UPI on Sunday!*\n\n🙏 You may participate in more quizzes by donating another ₹1.\n\n*JazakAllah Khair!*",
                parse_mode="Markdown",
                reply_markup=get_keyboard(chat_id)
            )
        else:
            # Failed - wrong answer
            send_telegram_message(
                chat_id,
                f"❌ *Quiz Failed!*\n\nYour score: {score}/{QUESTIONS_PER_QUIZ}\n\n📝 *Try next time by donating ₹{DONATION_AMOUNT//100}.*\n\nClick '💳 Donate ₹{DONATION_AMOUNT//100}' to try another quiz with NEW questions!\n\n🙏 Your donation helps disabled and calamity-hit people.",
                parse_mode="Markdown",
                reply_markup=get_keyboard(chat_id)
            )
        
        users[str(chat_id)]["quiz_active"] = False
        set_user_state(chat_id, None)
        save_users(users)
        return
    
    q = questions[index]
    set_user_data(chat_id, "current_q", q)
    set_user_data(chat_id, "current_q_index", index)
    
    text = f"🎯 *Question {index+1}/{QUESTIONS_PER_QUIZ}*\n\n{q['text']}\n\n"
    for i, opt in enumerate(q["options"]):
        text += f"{chr(65+i)}. {opt}\n"
    text += "\n*Reply with A, B, C, or D*"
    
    send_telegram_message(chat_id, text, parse_mode="Markdown")

def handle_quiz_answer(chat_id, answer):
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
        
        # Add question to answered list
        if q["id"] not in users[str(chat_id)].get("answered_questions", []):
            users[str(chat_id)]["answered_questions"] = users[str(chat_id)].get("answered_questions", []) + [q["id"]]
        
        save_users(users)
        send_question(chat_id, q_index + 1)
    else:
        # Wrong answer - quiz ends immediately
        send_telegram_message(
            chat_id,
            f"❌ *Wrong Answer!*\n\nCorrect answer: {q.get('correct')}\n\n📝 *Try next time by donating ₹{DONATION_AMOUNT//100}.*\n\nClick '💳 Donate ₹{DONATION_AMOUNT//100}' to try another quiz with NEW questions!\n\n🙏 Your donation helps disabled and calamity-hit people.",
            parse_mode="Markdown",
            reply_markup=get_keyboard(chat_id)
        )
        
        users[str(chat_id)]["quiz_active"] = False
        set_user_state(chat_id, None)
        save_users(users)  # FIXED: was save_users(chat_id)
        return

# ========== ADMIN COMMANDS ==========
async def admin_stats(update, context):
    chat_id = update.effective_user.id
    if chat_id != ADMIN_ID:
        await update.message.reply_text("⛔ Not authorized.")
        return
    
    users = load_users()
    winners = load_winners()
    
    total_users = len(users)
    total_donations = sum(u.get("total_donations", 0) for u in users.values())
    total_wins = sum(u.get("wins", 0) for u in users.values())
    pending_winners = len([w for w in winners if w.get("status") == "Pending"])
    
    stats_text = f"""
📊 *Admin Statistics*

👥 Total Registered Users: {total_users}
💰 Total Donations: ₹{total_donations}
🏆 Total Wins: {total_wins}
⏳ Pending Payouts: {pending_winners}

*Commands:*
/admin_users - View all users
/admin_winners - View winners list
/mark_paid USER_ID - Mark winner as paid
/add_question Q? Opt1 Opt2 Opt3 Opt4 Correct
"""
    await update.message.reply_text(stats_text, parse_mode="Markdown")

async def admin_users(update, context):
    chat_id = update.effective_user.id
    if chat_id != ADMIN_ID:
        await update.message.reply_text("⛔ Not authorized.")
        return
    
    users = load_users()
    
    if not users:
        await update.message.reply_text("No users registered yet.")
        return
    
    text = "*📋 Registered Users*\n\n"
    for uid, user in list(users.items())[:20]:
        text += f"🆔 `{uid}`\n"
        text += f"   📱 {user.get('phone', 'N/A')}\n"
        text += f"   👤 {user.get('name', 'Not set')}\n"
        text += f"   📍 {user.get('place', 'Not set')}\n"
        text += f"   💸 UPI: {user.get('upi_id', 'Not set')}\n"
        text += f"   💰 Donations: ₹{user.get('total_donations', 0)}\n"
        text += f"   🏆 Wins: {user.get('wins', 0)}\n\n"
    
    await update.message.reply_text(text, parse_mode="Markdown")

async def admin_winners(update, context):
    chat_id = update.effective_user.id
    if chat_id != ADMIN_ID:
        await update.message.reply_text("⛔ Not authorized.")
        return
    
    winners = load_winners()
    
    if not winners:
        await update.message.reply_text("No winners yet.")
        return
    
    text = "*🏆 Winners List*\n\n"
    for w in winners[::-1][:20]:  # Show most recent first
        status_emoji = "⏳" if w.get("status") == "Pending" else "✅"
        text += f"{status_emoji} *User:* `{w.get('telegram_id')}`\n"
        text += f"   👤 {w.get('name', 'Unknown')}\n"
        text += f"   📱 {w.get('phone', 'Unknown')}\n"
        text += f"   💸 UPI: {w.get('upi', 'Not set')}\n"
        text += f"   📅 {w.get('date', 'Unknown')[:10]}\n"
        text += f"   Status: {w.get('status', 'Pending')}\n\n"
    
    await update.message.reply_text(text, parse_mode="Markdown")

async def mark_paid(update, context):
    chat_id = update.effective_user.id
    if chat_id != ADMIN_ID:
        await update.message.reply_text("⛔ Not authorized.")
        return
    
    args = context.args
    if len(args) < 1:
        await update.message.reply_text("❌ Usage: /mark_paid USER_ID")
        return
    
    user_id = args[0]
    winners = load_winners()
    
    found = False
    for w in winners:
        if str(w.get("telegram_id")) == user_id and w.get("status") == "Pending":
            w["status"] = "Paid"
            found = True
            break
    
    if found:
        save_winners(winners)
        await update.message.reply_text(f"✅ Winner {user_id} marked as PAID!")
        
        send_telegram_message(
            int(user_id),
            "✅ *Prize Payment Completed!* 🎉\n\n🏆 *Jannat Foundation has sent your prize to your UPI ID!*\n\n📅 Payment completed as promised.\n\n*JazakAllah Khair for participating!*",
            parse_mode="Markdown"
        )
    else:
        await update.message.reply_text(f"❌ Winner {user_id} not found or already paid.")

async def add_question(update, context):
    chat_id = update.effective_user.id
    if chat_id != ADMIN_ID:
        await update.message.reply_text("⛔ Not authorized.")
        return
    
    args = context.args
    if len(args) < 6:
        await update.message.reply_text(
            "❌ Usage:\n/add_question \"Question\" \"Opt1\" \"Opt2\" \"Opt3\" \"Opt4\" \"Correct\"\n\nExample:\n/add_question \"What is 2+2?\" \"3\" \"4\" \"5\" \"6\" \"4\""
        )
        return
    
    questions = load_questions()
    new_id = max([q["id"] for q in questions], default=0) + 1
    
    new_q = {
        "id": new_id,
        "text": args[0],
        "options": [args[1], args[2], args[3], args[4]],
        "correct": args[5]
    }
    questions.append(new_q)
    save_questions(questions)
    
    await update.message.reply_text(f"✅ Question added!\nID: {new_id}\nQuestion: {args[0]}")

# ========== MAIN ==========
def main():
    global telegram_application
    
    if not TOKEN:
        print("❌ No BOT_TOKEN!")
        return
    
    print("🤖 Jannat Foundation Quiz Bot starting...")
    print(f"💰 Donation amount: ₹{DONATION_AMOUNT//100}")
    
    # Initialize files
    if not os.path.exists("users.json"):
        save_users({})
    if not os.path.exists("questions.json"):
        save_questions(load_questions())
    if not os.path.exists("winners.json"):
        save_winners([])
    
    # Start Flask
    Thread(target=start_flask, daemon=True).start()
    print("✅ Flask server started")
    
    # Build Telegram application
    telegram_application = Application.builder().token(TOKEN).build()
    
    # Add admin command handlers
    telegram_application.add_handler(CommandHandler("stats", admin_stats))
    telegram_application.add_handler(CommandHandler("admin_users", admin_users))
    telegram_application.add_handler(CommandHandler("admin_winners", admin_winners))
    telegram_application.add_handler(CommandHandler("mark_paid", mark_paid))
    telegram_application.add_handler(CommandHandler("add_question", add_question))
    
    # Set webhook
    webhook_url = "https://jannat-quiz-bot.onrender.com/webhook"
    
    async def setup_webhook():
        await telegram_application.bot.set_webhook(webhook_url)
        print(f"✅ Webhook set to: {webhook_url}")
        
        # Verify webhook
        webhook_info = await telegram_application.bot.get_webhook_info()
        print(f"📡 Webhook info: {webhook_info.url}")
    
    import asyncio
    asyncio.run(setup_webhook())
    
    # Start the application
    print("✅ Bot ready!")
    print("📡 Endpoints:")
    print("   - Telegram webhook: https://jannat-quiz-bot.onrender.com/webhook")
    print("   - Razorpay webhook: https://jannat-quiz-bot.onrender.com/razorpay-webhook")
    print("   - Webhook test: https://jannat-quiz-bot.onrender.com/webhook-test")
    
    # Start the application with polling (for admin commands) and webhook for updates
    telegram_application.run_webhook(
        listen="0.0.0.0",
        port=int(os.environ.get("PORT", 10000)),
        webhook_url=webhook_url,
        secret_token=None,
        drop_pending_updates=True
    )

if __name__ == "__main__":
    main()

import os
import json
import logging
import hashlib
import random
import requests
import asyncio
import shutil
from datetime import datetime
from threading import Thread
from io import BytesIO

from flask import Flask, request, jsonify
from telegram import Update, ReplyKeyboardMarkup, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, CallbackQueryHandler

import razorpay
from PIL import Image, ImageDraw, ImageFont

# ========== CONFIGURATION ==========
# Main Quiz Bot Token (@Jannat_Foundationbot)
MAIN_BOT_TOKEN = os.environ.get("BOT_TOKEN")
# Admin Bot Token (@JannatAdmin_bot)
ADMIN_BOT_TOKEN = os.environ.get("ADMIN_BOT_TOKEN", "")
# Lobby Bot Token (@Jannatcommunity_bot)
LOBBY_BOT_TOKEN = os.environ.get("LOBBY_BOT_TOKEN", "")
RAZORPAY_KEY_ID = os.environ.get("RAZORPAY_KEY_ID")
RAZORPAY_KEY_SECRET = os.environ.get("RAZORPAY_KEY_SECRET")
ADMIN_ID = int(os.environ.get("ADMIN_ID", "0"))

# Maintenance mode
BOT_MAINTENANCE = False

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

# ========== LOAD QUESTIONS FROM JSON FILE ==========
def load_questions():
    if os.path.exists("questions.json"):
        try:
            with open("questions.json", 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Error loading questions: {e}")
            return {"easy": [], "medium": [], "hard": []}
    return {"easy": [], "medium": [], "hard": []}

def get_random_question_by_difficulty(level):
    questions = load_questions()
    level_questions = questions.get(level, [])
    if level_questions:
        return random.choice(level_questions)
    return None

# ========== CREATE QUESTION IMAGE (Protect from copy) ==========
def create_question_image(question_text, options, question_number):
    """Create an image from question text and options to prevent copying"""
    try:
        # Create image
        img = Image.new('RGB', (900, 500), color='white')
        draw = ImageDraw.Draw(img)
        
        # Try to use a font, fallback to default
        try:
            font_title = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 28)
            font_text = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 24)
        except:
            font_title = ImageFont.load_default()
            font_text = ImageFont.load_default()
        
        # Draw question header
        draw.text((30, 20), f"Question {question_number}/3", fill='black', font=font_title)
        draw.text((30, 70), "─" * 40, fill='gray', font=font_text)
        
        # Draw question text (wrap if too long)
        y_pos = 110
        words = question_text.split()
        lines = []
        current_line = ""
        for word in words:
            test_line = current_line + " " + word if current_line else word
            if len(test_line) <= 60:
                current_line = test_line
            else:
                lines.append(current_line)
                current_line = word
        if current_line:
            lines.append(current_line)
        
        for line in lines:
            draw.text((30, y_pos), line, fill='black', font=font_text)
            y_pos += 35
        
        y_pos += 20
        
        # Draw options
        option_labels = ['A', 'B', 'C', 'D']
        for i, opt in enumerate(options):
            draw.text((30, y_pos + (i * 40)), f"{option_labels[i]}. {opt}", fill='black', font=font_text)
        
        # Draw instruction
        draw.text((30, y_pos + 180), "Reply with A, B, C, or D", fill='gray', font=font_text)
        
        # Save to bytes
        img_bytes = BytesIO()
        img.save(img_bytes, format='PNG')
        img_bytes.seek(0)
        
        return img_bytes
    except Exception as e:
        logger.error(f"Error creating image: {e}")
        return None

# ========== AUTO BACKUP FUNCTION ==========
def auto_backup_users():
    try:
        if os.path.exists("users.json"):
            if not os.path.exists("backups"):
                os.makedirs("backups")
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            backup_file = f"backups/users_backup_{timestamp}.json"
            shutil.copy("users.json", backup_file)
            backups = sorted([f for f in os.listdir("backups") if f.startswith("users_backup_")])
            for old in backups[:-20]:
                os.remove(os.path.join("backups", old))
            logger.info(f"✅ Auto-backup created")
    except Exception as e:
        logger.error(f"Backup failed: {e}")

# ========== ADMIN WINNER NOTIFICATION ==========
def notify_admin_winner(chat_id):
    """Send notification to admin when user completes quiz with 3/3"""
    users = load_users()
    u = users.get(str(chat_id), {})
    
    msg = f"""
🏆 *NEW QUIZ WINNER!* 🏆

🆔 TG ID: `{chat_id}`
👨 Name: {u.get('name', 'Not set')}
📍 Place: {u.get('place', 'Not set')}
📱 Phone: {u.get('phone', 'Not set')}
📧 Email: {u.get('email', 'Not set')}
💸 UPI: {u.get('upi_id', 'Not set')}

⭐ Score: 3/3
💰 Prize: ₹1000
📅 Eligible for Sunday payout

❤️ *Jannat Foundation*
"""
    send_telegram_message(ADMIN_BOT_TOKEN, ADMIN_ID, msg, parse_mode="Markdown")

# ========== LOBBY BOT (COMMUNITY BOT) WEBHOOK - FIXED LINK ==========
@web_app.route("/lobby-webhook", methods=["POST"])
def lobby_webhook():
    try:
        update_data = request.get_json()
        if update_data and 'message' in update_data:
            message = update_data['message']
            chat_id = message['chat']['id']
            text = message.get('text', '')
            
            logger.info(f"🏠 Lobby Bot - Message from {chat_id}: {text}")
            
            if text == '/start':
                send_lobby_welcome(chat_id)
            elif text == "ℹ️ About Foundation":
                send_lobby_about(chat_id)
            elif text == "📢 Share":
                send_share_options(chat_id)
            elif text == "🔙 Main Menu":
                send_lobby_welcome(chat_id)
        
        elif 'callback_query' in update_data:
            callback = update_data['callback_query']
            chat_id = callback['message']['chat']['id']
            data = callback.get('data', '')
            
            if data == "about":
                send_lobby_about(chat_id)
            elif data == "share":
                send_share_options(chat_id)
            elif data == "main_menu":
                send_lobby_welcome(chat_id)
            
            send_telegram_message(LOBBY_BOT_TOKEN, chat_id, "", method="answerCallbackQuery", callback_id=callback['id'])
        
        return "OK", 200
    except Exception as e:
        logger.error(f"Lobby webhook error: {e}")
        return "Error", 500

def send_lobby_welcome(chat_id):
    welcome_msg = """
🏆 *WELCOME TO JANNAT FOUNDATION* 🏆

🤝 *Our Mission:*
Helping needy people through small donations

💰 *Your Contribution:*
Just ₹1 donation helps us serve the community

🎁 *Your Reward:*
After donation, you can play our quiz and WIN ₹1000!

👇 *Click the button below to start the quiz* 👇
"""
    # FIXED: Using simpler URL without ?start parameter for better reliability
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🎮 Start Quiz", url="https://t.me/Jannat_Foundationbot")],
        [InlineKeyboardButton("ℹ️ About Foundation", callback_data="about"), InlineKeyboardButton("📢 Share", callback_data="share")],
        [InlineKeyboardButton("🔙 Main Menu", callback_data="main_menu")]
    ])
    send_telegram_message(LOBBY_BOT_TOKEN, chat_id, welcome_msg, parse_mode="Markdown", reply_markup=keyboard)

def send_lobby_about(chat_id):
    about_msg = """
📖 *About Jannat Foundation*

Jannat Foundation is a charitable trust dedicated to helping needy people across India.

*Our Programs:*
• 🍽️ Food distribution
• 📚 Education support
• 💊 Medical assistance
• 🚨 Emergency relief

*Your ₹1 donation directly helps:*
• Feed a hungry child
• Support education
• Provide basic medicine

*The Quiz:*
As a thank you, donors can participate in our quiz and win ₹1000 cash prize!

*Contact:* @imtiazs37

*Join us in making a difference!* 🤝
"""
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🎮 Start Quiz", url="https://t.me/Jannat_Foundationbot")],
        [InlineKeyboardButton("🔙 Main Menu", callback_data="main_menu")]
    ])
    send_telegram_message(LOBBY_BOT_TOKEN, chat_id, about_msg, parse_mode="Markdown", reply_markup=keyboard)

def send_share_options(chat_id):
    share_msg = (
        "📢 *Share with your friends!*\n\n"
        "🔗 **Join our community:**\n"
        "https://t.me/Jannatcommunity_bot\n\n"
        "🎮 **Play the quiz & win ₹1000:**\n"
        "https://t.me/Jannat_Foundationbot\n\n"
        "❤️ *Help us reach more people!*\n\n"
        "_Copy and share these links with your friends!_"
    )
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔙 Main Menu", callback_data="main_menu")]
    ])
    send_telegram_message(LOBBY_BOT_TOKEN, chat_id, share_msg, parse_mode="Markdown", reply_markup=keyboard)

# ========== TELEGRAM WEBHOOK ROUTE (Main Quiz Bot) ==========
@web_app.route("/webhook", methods=["POST"])
def telegram_webhook():
    global BOT_MAINTENANCE
    try:
        update_data = request.get_json()
        if update_data and 'message' in update_data:
            message = update_data['message']
            chat_id = message['chat']['id']
            text = message.get('text', '')
            logger.info(f"📱 Main Bot - Message from {chat_id}: {text}")
            
            if BOT_MAINTENANCE and chat_id != ADMIN_ID:
                send_telegram_message(MAIN_BOT_TOKEN, chat_id, "🔧 *Quiz is under maintenance for sometime.*\n\nPlease try again later.", parse_mode="Markdown")
                return "OK", 200
            
            if text == '/start':
                send_telegram_message(MAIN_BOT_TOKEN, chat_id, get_start_message())
                send_keyboard(MAIN_BOT_TOKEN, chat_id)
            elif text == "📝 Register":
                set_user_state(chat_id, "awaiting_phone")
                send_telegram_message(MAIN_BOT_TOKEN, chat_id, "📝 Send your *Phone Number*:\nExample: 9876543210", parse_mode="Markdown")
            elif text == "👤 Profile":
                show_profile(chat_id)
            elif text == "🎯 Demo Quiz":
                send_demo_quiz(chat_id)
            elif text == "ℹ️ About":
                send_telegram_message(MAIN_BOT_TOKEN, chat_id, get_about_message(), parse_mode="Markdown")
            elif text == "💳 Donate ₹1":
                create_payment(chat_id)
            elif text == "💸 Set UPI":
                set_user_state(chat_id, "awaiting_upi")
                send_telegram_message(MAIN_BOT_TOKEN, chat_id, "💸 Send your *UPI ID*:\nExample: username@okhdfcbank", parse_mode="Markdown")
            elif text in ["🔓 Start Quiz", "🔒 Start Quiz", "Start Quiz"]:
                start_quiz(chat_id)
            elif text == "NEXT":
                next_question(chat_id)
            elif text.startswith("✏️ Name "):
                update_profile_field(chat_id, text, "name")
            elif text.startswith("📍 Place "):
                update_profile_field(chat_id, text, "place")
            elif text.startswith("📧 Email "):
                update_profile_field(chat_id, text, "email")
            else:
                user_state = get_user_state(chat_id)
                if user_state == "awaiting_phone":
                    set_user_data(chat_id, "temp_phone", text)
                    set_user_state(chat_id, "awaiting_password")
                    send_telegram_message(MAIN_BOT_TOKEN, chat_id, "📝 Send your *Password* (min 4 chars):", parse_mode="Markdown")
                elif user_state == "awaiting_password":
                    complete_registration(chat_id, text)
                elif user_state == "awaiting_upi":
                    save_upi(chat_id, text)
                elif user_state == "awaiting_demo":
                    handle_demo_answer(chat_id, text)
                elif user_state == "quiz_active":
                    handle_quiz_answer(chat_id, text)
                else:
                    send_telegram_message(MAIN_BOT_TOKEN, chat_id, "Please use the buttons below.", reply_markup=get_keyboard(chat_id))
        return "OK", 200
    except Exception as e:
        logger.error(f"Main webhook error: {e}")
        return "Error", 500

# ========== ADMIN BOT WEBHOOK ROUTE ==========
@web_app.route("/admin-webhook", methods=["POST"])
def admin_webhook():
    try:
        update_data = request.get_json()
        if update_data and 'message' in update_data:
            message = update_data['message']
            chat_id = message['chat']['id']
            text = message.get('text', '')
            
            if chat_id != ADMIN_ID:
                send_telegram_message(ADMIN_BOT_TOKEN, chat_id, "⛔ This bot is for admin only.")
                return "OK", 200
            
            logger.info(f"🤖 Admin Bot - Command: {text}")
            
            if text == '/start':
                send_admin_keyboard(chat_id)
            elif text == "📊 Statistics":
                send_admin_stats(chat_id)
            elif text == "✅ Verify User":
                set_user_state(chat_id, "admin_awaiting_userid")
                send_telegram_message(ADMIN_BOT_TOKEN, chat_id, "📝 Send the User ID to verify:")
            elif text == "📢 Broadcast":
                set_user_state(chat_id, "admin_awaiting_broadcast")
                send_telegram_message(ADMIN_BOT_TOKEN, chat_id, "📝 Send the message to broadcast:")
            elif text == "🏆 Winners":
                send_winners_panel(chat_id)
            elif text == "📥 Export Data":
                export_users_data(chat_id)
            elif text == "🔧 Stop Bot":
                stop_maintenance_mode(chat_id)
            elif text == "▶️ Start Bot":
                start_maintenance_mode(chat_id)
            elif text == "💾 Backup Now":
                manual_backup(chat_id)
            elif text == "🔙 Main Menu":
                send_admin_keyboard(chat_id)
            else:
                user_state = get_user_state(chat_id)
                if user_state == "admin_awaiting_userid":
                    verify_user_command(chat_id, text)
                elif user_state == "admin_awaiting_broadcast":
                    broadcast_message(chat_id, text)
                else:
                    send_admin_keyboard(chat_id)
        return "OK", 200
    except Exception as e:
        logger.error(f"Admin webhook error: {e}")
        return "Error", 500

# ========== RAZORPAY WEBHOOK ==========
@web_app.route("/razorpay-webhook", methods=["POST"])
def razorpay_webhook():
    try:
        payload = request.get_json()
        logger.info(f"🔔 RAZORPAY WEBHOOK RECEIVED")
        event = payload.get("event", "")
        if event in ["payment_link.paid", "payment.captured"]:
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
            if telegram_id:
                mark_user_paid(telegram_id, amount)
        return jsonify({"status": "success"}), 200
    except Exception as e:
        logger.error(f"Razorpay webhook error: {e}")
        return jsonify({"error": str(e)}), 500

# ========== PAYMENT SUCCESS PAGE ==========
@web_app.route("/payment-success", methods=["GET"])
def payment_success():
    return """
    <!DOCTYPE html>
    <html>
    <head><title>Donation Received</title></head>
    <body style="text-align: center; padding: 50px;">
        <h1>✅ Thank you for your Donation!</h1>
        <p>Return to Telegram and press Start Quiz.</p>
    </body>
    </html>
    """

@web_app.route("/webhook-test", methods=["GET"])
def webhook_test():
    return jsonify({"status": "alive", "bot": "Main Quiz Bot"})

@web_app.route("/admin-webhook-test", methods=["GET"])
def admin_webhook_test():
    return jsonify({"status": "alive", "bot": "Admin Bot"})

@web_app.route("/lobby-webhook-test", methods=["GET"])
def lobby_webhook_test():
    return jsonify({"status": "alive", "bot": "Lobby/Community Bot"})

@web_app.route("/")
def home():
    return """
    <h1>Jannat Foundation Quiz Bot</h1>
    <p>✅ Main Quiz Bot: @Jannat_Foundationbot</p>
    <p>✅ Admin Bot: @JannatAdmin_bot</p>
    <p>✅ Community/Lobby Bot: @Jannatcommunity_bot</p>
    """

def start_flask():
    port = int(os.environ.get("PORT", 10000))
    web_app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)

# ========== HELPER FUNCTIONS ==========
def send_telegram_message(bot_token, chat_id, text, reply_markup=None, parse_mode="Markdown", method="sendMessage", callback_id=None):
    if method == "answerCallbackQuery":
        url = f"https://api.telegram.org/bot{bot_token}/answerCallbackQuery"
        data = {"callback_query_id": callback_id}
        try:
            requests.post(url, json=data)
        except:
            pass
        return
    
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    data = {"chat_id": chat_id, "text": text, "parse_mode": parse_mode}
    if reply_markup:
        if isinstance(reply_markup, dict):
            data["reply_markup"] = reply_markup
        else:
            data["reply_markup"] = reply_markup.to_dict()
    try:
        response = requests.post(url, json=data)
        return response.json()
    except Exception as e:
        logger.error(f"Failed to send: {e}")
        return None

def send_telegram_photo(bot_token, chat_id, photo_bytes, caption=None, reply_markup=None):
    """Send photo to Telegram"""
    url = f"https://api.telegram.org/bot{bot_token}/sendPhoto"
    files = {'photo': ('question.png', photo_bytes, 'image/png')}
    data = {'chat_id': chat_id}
    if caption:
        data['caption'] = caption
    if reply_markup:
        data['reply_markup'] = json.dumps(reply_markup)
    try:
        response = requests.post(url, files=files, data=data)
        return response.json()
    except Exception as e:
        logger.error(f"Failed to send photo: {e}")
        return None

def send_telegram_document(bot_token, chat_id, file_path, caption=""):
    url = f"https://api.telegram.org/bot{bot_token}/sendDocument"
    try:
        with open(file_path, 'rb') as f:
            files = {'document': f}
            data = {'chat_id': chat_id, 'caption': caption}
            response = requests.post(url, files=files, data=data)
            return response.json()
    except Exception as e:
        logger.error(f"Failed to send document: {e}")
        return None

def send_keyboard(bot_token, chat_id):
    keyboard = {
        "keyboard": [
            ["📝 Register", "👤 Profile"],
            ["🎯 Demo Quiz", "ℹ️ About"],
            ["💳 Donate ₹1", "💸 Set UPI"],
            ["🔒 Start Quiz"]
        ],
        "resize_keyboard": True
    }
    send_telegram_message(bot_token, chat_id, "Use the buttons below:", reply_markup=keyboard)

def get_keyboard(chat_id):
    users = load_users()
    is_registered = str(chat_id) in users and users[str(chat_id)].get("registered", False)
    has_paid = is_registered and users[str(chat_id)].get("payment_completed", False)
    keyboard = [
        ["📝 Register", "👤 Profile"],
        ["🎯 Demo Quiz", "ℹ️ About"],
        ["💳 Donate ₹1", "💸 Set UPI"],
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

Contact: @imtiazs37
"""

# ========== ADMIN FUNCTIONS ==========
def send_admin_keyboard(chat_id):
    keyboard = {
        "keyboard": [
            ["📊 Statistics", "✅ Verify User"],
            ["📢 Broadcast", "🏆 Winners"],
            ["📥 Export Data", "💾 Backup Now"],
            ["🔧 Stop Bot", "▶️ Start Bot"],
            ["🔙 Main Menu"]
        ],
        "resize_keyboard": True
    }
    msg = "🔐 *Admin Control Panel*\n\nUse the buttons below to manage the bot."
    send_telegram_message(ADMIN_BOT_TOKEN, chat_id, msg, parse_mode="Markdown", reply_markup=keyboard)

def get_admin_keyboard():
    return {
        "keyboard": [
            ["📊 Statistics", "✅ Verify User"],
            ["📢 Broadcast", "🏆 Winners"],
            ["📥 Export Data", "💾 Backup Now"],
            ["🔧 Stop Bot", "▶️ Start Bot"],
            ["🔙 Main Menu"]
        ],
        "resize_keyboard": True
    }

def send_admin_stats(chat_id):
    users = load_users()
    registered = sum(1 for u in users.values() if u.get("registered", False))
    paid = sum(1 for u in users.values() if u.get("payment_completed"))
    winners = sum(1 for u in users.values() if u.get("current_quiz_score", 0) == 3)
    msg = f"📊 *Statistics*\n\n👥 Registered: {registered}\n💰 Donated: {paid}\n🏆 Winners: {winners}"
    send_telegram_message(ADMIN_BOT_TOKEN, chat_id, msg, parse_mode="Markdown", reply_markup=get_admin_keyboard())

def send_winners_panel(chat_id):
    users = load_users()
    winners = []
    for uid, user in users.items():
        if user.get("current_quiz_score", 0) == 3 and user.get("payment_completed"):
            winners.append({
                "id": uid,
                "name": user.get("name", "Not set"),
                "place": user.get("place", "Not set"),
                "upi": user.get("upi_id", "Not set"),
                "score": user.get("current_quiz_score", 0)
            })
    if not winners:
        send_telegram_message(ADMIN_BOT_TOKEN, chat_id, "No winners yet.", reply_markup=get_admin_keyboard())
        return
    winner_text = "🏆 *WINNERS LIST* 🏆\n\n"
    for w in winners:
        winner_text += f"👤 *{w['name']}*\n📍 {w['place']}\n💸 `{w['upi']}`\n🆔 {w['id']}\n⭐ {w['score']}/3\n\n"
    send_telegram_message(ADMIN_BOT_TOKEN, chat_id, winner_text, parse_mode="Markdown", reply_markup=get_admin_keyboard())

def export_users_data(chat_id):
    if os.path.exists("users.json"):
        send_telegram_document(ADMIN_BOT_TOKEN, chat_id, "users.json", "📊 User Data Export")
    else:
        send_telegram_message(ADMIN_BOT_TOKEN, chat_id, "No data file found.", reply_markup=get_admin_keyboard())

def manual_backup(chat_id):
    auto_backup_users()
    send_telegram_message(ADMIN_BOT_TOKEN, chat_id, "✅ Manual backup completed!\n📁 Saved in backups folder.", reply_markup=get_admin_keyboard())

def verify_user_command(chat_id, user_id):
    users = load_users()
    if user_id not in users:
        send_telegram_message(ADMIN_BOT_TOKEN, chat_id, f"❌ User {user_id} not found.", reply_markup=get_admin_keyboard())
        set_user_state(chat_id, None)
        return
    users[user_id]["payment_completed"] = True
    users[user_id]["quiz_locked"] = False
    save_users(users)
    send_telegram_message(ADMIN_BOT_TOKEN, chat_id, f"✅ Verified user {user_id}!", reply_markup=get_admin_keyboard())
    set_user_state(chat_id, None)
    send_telegram_message(MAIN_BOT_TOKEN, int(user_id), "✅ *Payment Verified!* 🔓 Quiz UNLOCKED!\n\nPress '🔓 Start Quiz' to play!", parse_mode="Markdown")

def broadcast_message(chat_id, message):
    users = load_users()
    sent = 0
    for uid in users.keys():
        try:
            send_telegram_message(MAIN_BOT_TOKEN, int(uid), f"📢 *Announcement*\n\n{message}", parse_mode="Markdown")
            sent += 1
        except:
            pass
    send_telegram_message(ADMIN_BOT_TOKEN, chat_id, f"✅ Broadcast sent to {sent} users", reply_markup=get_admin_keyboard())
    set_user_state(chat_id, None)

def stop_maintenance_mode(chat_id):
    global BOT_MAINTENANCE
    BOT_MAINTENANCE = True
    send_telegram_message(ADMIN_BOT_TOKEN, chat_id, "🔧 *Maintenance Mode ENABLED*\n\nUsers will see maintenance message.", parse_mode="Markdown", reply_markup=get_admin_keyboard())

def start_maintenance_mode(chat_id):
    global BOT_MAINTENANCE
    BOT_MAINTENANCE = False
    send_telegram_message(ADMIN_BOT_TOKEN, chat_id, "✅ *Maintenance Mode DISABLED*\n\nBot is active again.", parse_mode="Markdown", reply_markup=get_admin_keyboard())

def mark_user_paid(telegram_id, amount):
    users = load_users()
    telegram_id_str = str(telegram_id)
    if telegram_id_str not in users:
        logger.warning(f"User {telegram_id_str} not found")
        return
    users[telegram_id_str]["payment_completed"] = True
    users[telegram_id_str]["quiz_locked"] = False
    save_users(users)
    auto_backup_users()
    logger.info(f"✅ User {telegram_id_str} marked as paid")
    keyboard = {
        "keyboard": [
            ["📝 Register", "👤 Profile"],
            ["🎯 Demo Quiz", "ℹ️ About"],
            ["💳 Donate ₹1", "💸 Set UPI"],
            ["🔓 Start Quiz"]
        ],
        "resize_keyboard": True
    }
    send_telegram_message(MAIN_BOT_TOKEN, int(telegram_id), f"✅ *Thank you for your Donation!* 🎉\n\n💰 Amount: ₹{amount}\n\n🔓 *Quiz UNLOCKED!*\n\nPress '🔓 Start Quiz' to play!", parse_mode="Markdown", reply_markup=keyboard)

# ========== DATA FUNCTIONS ==========
def load_users():
    if os.path.exists("users.json"):
        try:
            with open("users.json", 'r', encoding='utf-8') as f:
                return json.load(f)
        except:
            return {}
    return {}

def save_users(users):
    try:
        with open("users.json", 'w', encoding='utf-8') as f:
            json.dump(users, f, indent=2, ensure_ascii=False)
        auto_backup_users()
    except Exception as e:
        logger.error(f"Failed to save: {e}")

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

# ========== PROFILE COMPLETION CHECK ==========
def profile_complete(chat_id):
    users = load_users()
    user = users.get(str(chat_id), {})
    if not user.get("name"):
        return False
    if not user.get("place"):
        return False
    if not user.get("upi_id"):
        return False
    return True

def get_missing_fields(chat_id):
    users = load_users()
    user = users.get(str(chat_id), {})
    missing = []
    if not user.get("name"):
        missing.append("✏️ Name YourName")
    if not user.get("place"):
        missing.append("📍 Place YourCity")
    if not user.get("upi_id"):
        missing.append("💸 Set UPI (use the button)")
    return missing

def show_profile(chat_id):
    users = load_users()
    if str(chat_id) not in users:
        send_telegram_message(MAIN_BOT_TOKEN, chat_id, "❌ Register first.", reply_markup=get_keyboard(chat_id))
        return
    
    u = users[str(chat_id)]
    text = f"""
👤 *Your Profile*

🆔 TG ID: `{chat_id}`
📱 Phone: {u.get('phone', 'Not set')}
👨 Name: {u.get('name', 'Not set')}
📍 Place: {u.get('place', 'Not set')}
📧 Email: {u.get('email', 'Not set')}
💸 UPI: {u.get('upi_id', 'Not set')}
💰 Donated: {'✅ Yes' if u.get('payment_completed') else '❌ No'}
🏆 Score: {u.get('current_quiz_score', 0)}/3

*To update:*
✏️ Name YourName
📍 Place YourCity
📧 Email your@email.com
"""
    send_telegram_message(MAIN_BOT_TOKEN, chat_id, text, parse_mode="Markdown", reply_markup=get_keyboard(chat_id))

def update_profile_field(chat_id, text, field):
    users = load_users()
    if str(chat_id) not in users:
        send_telegram_message(MAIN_BOT_TOKEN, chat_id, "❌ Register first.", reply_markup=get_keyboard(chat_id))
        return
    parts = text.split(" ", 1)
    if len(parts) < 2:
        send_telegram_message(MAIN_BOT_TOKEN, chat_id, f"❌ Send: ✏️ Name YourName", reply_markup=get_keyboard(chat_id))
        return
    value = parts[1].strip()
    field_names = {"name": "Name", "place": "Place", "email": "Email"}
    users[str(chat_id)][field] = value
    save_users(users)
    send_telegram_message(MAIN_BOT_TOKEN, chat_id, f"✅ {field_names[field]} updated to: {value}", reply_markup=get_keyboard(chat_id))

def complete_registration(chat_id, password):
    if len(password) < 4:
        send_telegram_message(MAIN_BOT_TOKEN, chat_id, "❌ Password too short.", reply_markup=get_keyboard(chat_id))
        return
    users = load_users()
    phone = get_user_data(chat_id, "temp_phone")
    if str(chat_id) in users:
        send_telegram_message(MAIN_BOT_TOKEN, chat_id, "✅ Already registered!", reply_markup=get_keyboard(chat_id))
        return
    users[str(chat_id)] = {
        "phone": phone,
        "password": hash_password(password),
        "name": "", "place": "", "email": "", "upi_id": "",
        "payment_completed": False, "quiz_locked": False,
        "current_question_index": 0, "current_quiz_score": 0,
        "quiz_active": False, "waiting_next": False, "registered": True,
        "registered_on": datetime.now().isoformat()
    }
    save_users(users)
    set_user_state(chat_id, None)
    send_telegram_message(MAIN_BOT_TOKEN, chat_id, "✅ *Registration Successful!*", parse_mode="Markdown", reply_markup=get_keyboard(chat_id))

def save_upi(chat_id, upi_id):
    users = load_users()
    if str(chat_id) in users:
        users[str(chat_id)]["upi_id"] = upi_id
        save_users(users)
        set_user_state(chat_id, None)
        send_telegram_message(MAIN_BOT_TOKEN, chat_id, "✅ *UPI Saved!* 💰 ₹1000\n\n❤️ *Jannat Foundation will pay your prize on Sunday.*", parse_mode="Markdown", reply_markup=get_keyboard(chat_id))

def send_demo_quiz(chat_id):
    demo = {"question": "What is the capital of France?", "options": ["London", "Berlin", "Paris", "Madrid"], "correct": "Paris"}
    set_user_data(chat_id, "demo_q", demo)
    set_user_state(chat_id, "awaiting_demo")
    text = f"🎯 *DEMO QUIZ*\n\n⏱️ *15 Seconds*\n\n{demo['question']}\n\nA. London\nB. Berlin\nC. Paris\nD. Madrid\n\n*Reply A, B, C, or D*"
    send_telegram_message(MAIN_BOT_TOKEN, chat_id, text, parse_mode="Markdown")

def create_payment(chat_id):
    users = load_users()
    if str(chat_id) not in users:
        send_telegram_message(MAIN_BOT_TOKEN, chat_id, "❌ Register first.", reply_markup=get_keyboard(chat_id))
        return
    try:
        payment_link = razorpay_client.payment_link.create({
            "amount": 100, "currency": "INR",
            "description": f"Jannat Donation - User {chat_id}",
            "notes": {"telegram_id": str(chat_id)},
            "callback_url": "https://jannat-quiz-bot.onrender.com/payment-success",
            "callback_method": "get"
        })
        payment_url = payment_link["short_url"]
        send_telegram_message(MAIN_BOT_TOKEN, chat_id, f"💳 *Donate ₹1*\n\n🔗 [Click to Donate]({payment_url})\n\n✅ After donation, quiz unlocks!", parse_mode="Markdown", reply_markup=get_keyboard(chat_id))
    except Exception as e:
        logger.error(f"Donation error: {e}")
        send_telegram_message(MAIN_BOT_TOKEN, chat_id, f"❌ Error: {str(e)[:100]}", reply_markup=get_keyboard(chat_id))

# ========== QUIZ - WITH IMAGE PROTECTION ==========
def start_quiz(chat_id):
    users = load_users()
    
    if str(chat_id) not in users:
        send_telegram_message(MAIN_BOT_TOKEN, chat_id, "❌ Register first.", reply_markup=get_keyboard(chat_id))
        return
    
    user = users[str(chat_id)]
    
    if not user.get("payment_completed"):
        send_telegram_message(MAIN_BOT_TOKEN, chat_id, "❌ Donate ₹1 first.", reply_markup=get_keyboard(chat_id))
        return
    
    if user.get("quiz_locked"):
        send_telegram_message(MAIN_BOT_TOKEN, chat_id, "🔒 *Quiz Locked*\n\nYou have already completed the quiz.\n\nDonate ₹1 again to play a new set of questions!", reply_markup=get_keyboard(chat_id))
        return
    
    # Get questions - Easy, Medium, Hard (internal only)
    easy_q = get_random_question_by_difficulty("easy")
    medium_q = get_random_question_by_difficulty("medium")
    hard_q = get_random_question_by_difficulty("hard")
    
    if not easy_q or not medium_q or not hard_q:
        send_telegram_message(MAIN_BOT_TOKEN, chat_id, "❌ Questions not available. Please contact admin.", reply_markup=get_keyboard(chat_id))
        return
    
    users[str(chat_id)]["session_questions"] = [easy_q, medium_q, hard_q]
    users[str(chat_id)]["current_question_index"] = 0
    users[str(chat_id)]["current_quiz_score"] = 0
    users[str(chat_id)]["quiz_active"] = True
    users[str(chat_id)]["waiting_next"] = False
    save_users(users)
    set_user_state(chat_id, "quiz_active")
    
    send_question(chat_id, 0)

def send_question(chat_id, index):
    users = load_users()
    session_questions = users.get(str(chat_id), {}).get("session_questions", [])
    
    if index >= len(session_questions):
        score = users[str(chat_id)].get("current_quiz_score", 0)
        users[str(chat_id)]["quiz_active"] = False
        users[str(chat_id)]["quiz_locked"] = True
        save_users(users)
        set_user_state(chat_id, None)
        
        if score == 3:
            notify_admin_winner(chat_id)
        
        if not profile_complete(chat_id):
            missing_fields = get_missing_fields(chat_id)
            missing_text = "\n".join(missing_fields)
            send_telegram_message(MAIN_BOT_TOKEN, chat_id, f"🎉 *QUIZ COMPLETED!* 🎉\n\nYour score: {score}/3\n\n⚠️ *Before claiming your prize, please complete:*\n\n{missing_text}\n\nUse the Profile button to update your details.", parse_mode="Markdown", reply_markup=get_keyboard(chat_id))
        else:
            send_telegram_message(MAIN_BOT_TOKEN, chat_id, f"🎉 *QUIZ COMPLETED!* 🎉\n\nYour score: {score}/3\n\n🏆 Tap '💸 Set UPI' to claim ₹1000!\n\n❤️ *Jannat Foundation will pay your prize on Sunday.*\n\n*Donate ₹1 again to play a new quiz!*", parse_mode="Markdown", reply_markup=get_keyboard(chat_id))
        return
    
    q = session_questions[index]
    
    set_user_data(chat_id, "current_q", q)
    set_user_data(chat_id, "current_q_index", index)
    set_user_data(chat_id, "question_start_time", int(datetime.now().timestamp()))
    
    # Set time limit based on question number
    time_limit = 15 if index == 0 else 11
    
    # FIXED: Show time limit without countdown
    text = f"🎯 *Question {index+1}/3*\n\n⏱️ *{time_limit} Seconds*\n\n{q['text']}\n\nA. {q['options'][0]}\nB. {q['options'][1]}\nC. {q['options'][2]}\nD. {q['options'][3]}\n\n*Reply A, B, C, or D*"
    send_telegram_message(MAIN_BOT_TOKEN, chat_id, text, parse_mode="Markdown")

def handle_quiz_answer(chat_id, answer):
    users = load_users()
    
    if not users.get(str(chat_id), {}).get("quiz_active"):
        return
    if users.get(str(chat_id), {}).get("waiting_next"):
        send_telegram_message(MAIN_BOT_TOKEN, chat_id, "Press 'NEXT' for next question.")
        return
    
    # Check timeout with different limits per question
    question_start = get_user_data(chat_id, "question_start_time")
    if question_start:
        now = int(datetime.now().timestamp())
        q_index = get_user_data(chat_id, "current_q_index")
        # Question 1: 15 seconds, Question 2 & 3: 11 seconds
        allowed_time = 15 if q_index == 0 else 11
        if now - question_start > allowed_time:
            users[str(chat_id)]["quiz_active"] = False
            users[str(chat_id)]["quiz_locked"] = True
            save_users(users)
            set_user_state(chat_id, None)
            send_telegram_message(MAIN_BOT_TOKEN, chat_id, "⏰ *Time's Up!*\n\nYou didn't answer in time.\n\n💳 *Donate ₹1 to try again!*", parse_mode="Markdown", reply_markup=get_keyboard(chat_id))
            return
    
    q = get_user_data(chat_id, "current_q")
    q_index = get_user_data(chat_id, "current_q_index")
    
    if not q:
        set_user_state(chat_id, None)
        return
    
    letter_map = {"A": 0, "B": 1, "C": 2, "D": 3}
    if answer not in letter_map:
        send_telegram_message(MAIN_BOT_TOKEN, chat_id, "Reply with A, B, C, or D")
        return
    
    selected = q["options"][letter_map[answer]]
    
    if selected == q.get("correct"):
        users[str(chat_id)]["current_quiz_score"] = users[str(chat_id)].get("current_quiz_score", 0) + 1
        users[str(chat_id)]["waiting_next"] = True
        save_users(users)
        
        session_questions = users.get(str(chat_id), {}).get("session_questions", [])
        if q_index + 1 >= len(session_questions):
            # Last question - complete quiz
            users[str(chat_id)]["quiz_active"] = False
            users[str(chat_id)]["quiz_locked"] = True
            save_users(users)
            set_user_state(chat_id, None)
            
            score = users[str(chat_id)]["current_quiz_score"]
            
            # Send admin notification if perfect score
            if score == 3:
                notify_admin_winner(chat_id)
            
            if not profile_complete(chat_id):
                missing_fields = get_missing_fields(chat_id)
                missing_text = "\n".join(missing_fields)
                send_telegram_message(MAIN_BOT_TOKEN, chat_id, f"✅ *Correct!*\n\n🎉 *QUIZ COMPLETED!* 🎉\n\nYour score: {score}/3\n\n⚠️ *Before claiming your prize, please complete:*\n\n{missing_text}\n\nUse the Profile button to update your details.", parse_mode="Markdown", reply_markup=get_keyboard(chat_id))
            else:
                send_telegram_message(MAIN_BOT_TOKEN, chat_id, f"✅ *Correct!*\n\n🎉 *QUIZ COMPLETED!* 🎉\n\nYour score: {score}/3\n\n🏆 Tap '💸 Set UPI' to claim ₹1000!\n\n❤️ *Jannat Foundation will pay your prize on Sunday.*\n\n*Donate ₹1 again to play a new quiz!*", parse_mode="Markdown", reply_markup=get_keyboard(chat_id))
        else:
            missing = get_missing_fields(chat_id)
            msg = f"✅ *Correct!*\n\nPress 'NEXT' for Question {q_index + 2}"
            if missing:
                msg += "\n\n📝 *Please update these details:*\n" + "\n".join(missing)
                msg += "\n\nUse the Profile button to update."
            next_keyboard = {"keyboard": [["NEXT"]], "resize_keyboard": True}
            send_telegram_message(MAIN_BOT_TOKEN, chat_id, msg, reply_markup=next_keyboard)
    else:
        # Wrong answer - end quiz
        users[str(chat_id)]["quiz_active"] = False
        users[str(chat_id)]["quiz_locked"] = True
        save_users(users)
        set_user_state(chat_id, None)
        
        send_telegram_message(MAIN_BOT_TOKEN, chat_id, "❌ *Wrong Answer!*\n\n💳 *Try next time by donating ₹1*", parse_mode="Markdown", reply_markup=get_keyboard(chat_id))

def next_question(chat_id):
    users = load_users()
    
    if str(chat_id) not in users:
        return
    if not users[str(chat_id)].get("waiting_next"):
        send_telegram_message(MAIN_BOT_TOKEN, chat_id, "Answer the current question first!")
        return
    
    users[str(chat_id)]["waiting_next"] = False
    current_index = users[str(chat_id)].get("current_question_index", 0)
    current_index += 1
    users[str(chat_id)]["current_question_index"] = current_index
    save_users(users)
    
    send_question(chat_id, current_index)

# ========== MAIN ==========
def main():
    if not MAIN_BOT_TOKEN:
        print("❌ No MAIN_BOT_TOKEN!")
        return
    
    print("🤖 Jannat Foundation Bot Starting...")
    print(f"✅ Main Quiz Bot: @Jannat_Foundationbot")
    print(f"✅ Admin Bot: @JannatAdmin_bot")
    print(f"✅ Lobby Bot: @Jannatcommunity_bot")
    
    if not os.path.exists("users.json"):
        save_users({})
    if not os.path.exists("backups"):
        os.makedirs("backups")
    
    if not os.path.exists("questions.json"):
        print("⚠️ questions.json not found! Please create it with Easy, Medium, Hard questions.")
    else:
        questions = load_questions()
        easy_count = len(questions.get("easy", []))
        medium_count = len(questions.get("medium", []))
        hard_count = len(questions.get("hard", []))
        print(f"📚 Questions loaded: {easy_count} Easy, {medium_count} Medium, {hard_count} Hard")
    
    Thread(target=start_flask, daemon=True).start()
    print("✅ Flask server started")
    
    async def set_webhooks():
        # Main bot webhook
        main_app = Application.builder().token(MAIN_BOT_TOKEN).build()
        await main_app.bot.set_webhook("https://jannat-quiz-bot.onrender.com/webhook")
        print(f"✅ Main bot webhook set")
        
        # Admin bot webhook
        if ADMIN_BOT_TOKEN:
            admin_app = Application.builder().token(ADMIN_BOT_TOKEN).build()
            await admin_app.bot.set_webhook("https://jannat-quiz-bot.onrender.com/admin-webhook")
            print(f"✅ Admin bot webhook set")
        
        # Lobby bot webhook
        if LOBBY_BOT_TOKEN:
            lobby_app = Application.builder().token(LOBBY_BOT_TOKEN).build()
            await lobby_app.bot.set_webhook("https://jannat-quiz-bot.onrender.com/lobby-webhook")
            print(f"✅ Lobby/Community bot webhook set")
    
    asyncio.run(set_webhooks())
    
    print("\n" + "="*50)
    print("🎉 ALL BOTS ARE RUNNING!")
    print("="*50)
    print("\n📋 Bot Links:")
    print("   🎯 Quiz Bot: https://t.me/Jannat_Foundationbot")
    print("   🔐 Admin Bot: https://t.me/JannatAdmin_bot")
    print("   🏠 Community Bot: https://t.me/Jannatcommunity_bot")
    print("\n📋 For Ads, use: https://t.me/Jannatcommunity_bot?start=ad")
    print("="*50)
    
    import time
    while True:
        time.sleep(10)

if __name__ == "__main__":
    main()

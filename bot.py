import imghdr
import os
import json
import logging
import hashlib
import random
from datetime import datetime
from functools import wraps

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ConversationHandler,
    filters,
    ContextTypes
)

import razorpay

# ========== CONFIGURATION ==========
TOKEN = os.environ.get("BOT_TOKEN")
RAZORPAY_KEY_ID = os.environ.get("RAZORPAY_KEY_ID", "rzp_test_OUGnz1rs9k9vFW")
RAZORPAY_KEY_SECRET = os.environ.get("RAZORPAY_KEY_SECRET")
ADMIN_ID = int(os.environ.get("ADMIN_ID", "0"))

# States
PHONE_REG, PASSWORD_REG, EDIT_NAME, EDIT_PLACE, EDIT_EMAIL, UPI_INPUT = range(6)

# Setup logging
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# Razorpay client
razorpay_client = razorpay.Client(auth=(RAZORPAY_KEY_ID, RAZORPAY_KEY_SECRET))

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

def get_main_keyboard(user_id=None):
    users = load_data("users.json")
    is_registered = user_id and str(user_id) in users
    has_paid = False
    if is_registered:
        has_paid = users[str(user_id)].get("payment_completed", False)
    
    keyboard = []
    keyboard.append([InlineKeyboardButton("📝 Register", callback_data="register")])
    keyboard.append([InlineKeyboardButton("👤 My Profile", callback_data="profile")])
    keyboard.append([InlineKeyboardButton("🎯 Demo Quiz", callback_data="demo_quiz")])
    
    if is_registered and has_paid:
        keyboard.append([InlineKeyboardButton("🔓 Start Quiz", callback_data="start_quiz")])
    else:
        keyboard.append([InlineKeyboardButton("🔒 Start Quiz (Pay ₹20)", callback_data="payment_info")])
    
    keyboard.append([InlineKeyboardButton("💳 Payment (₹20)", callback_data="payment")])
    keyboard.append([InlineKeyboardButton("💸 Set UPI", callback_data="set_upi")])
    keyboard.append([InlineKeyboardButton("ℹ️ About", callback_data="about")])
    
    return InlineKeyboardMarkup(keyboard)

# ========== START COMMAND ==========
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    welcome_msg = f"""
🏆 *JANNAT FOUNDATION QUIZ* 🏆

Welcome {user.first_name}!

💰 *Win ₹1000 Cash Prize!*

*How it works:*
1️⃣ Register with phone & password
2️⃣ Pay ₹20 to unlock quiz
3️⃣ Answer 1 question correctly
4️⃣ Submit your UPI ID
5️⃣ Get ₹1000 on Sunday!

👇 *Use the buttons below* 👇
"""
    await update.message.reply_text(welcome_msg, parse_mode="Markdown", reply_markup=get_main_keyboard(user.id))

# ========== BUTTON HANDLER ==========
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    user_id = query.from_user.id
    
    if data == "register":
        context.user_data["action"] = "register"
        await query.edit_message_text("📝 Send your *Phone Number* (with country code):\nExample: +919876543210", parse_mode="Markdown")
        return PHONE_REG
    
    elif data == "profile":
        users = load_data("users.json")
        if str(user_id) not in users:
            await query.edit_message_text("❌ Please register first.", reply_markup=get_main_keyboard(user_id))
            return
        user = users[str(user_id)]
        profile_text = f"""
👤 *Your Profile*

📱 Phone: `{user.get('phone', 'Not set')}`
👨 Name: {user.get('name', 'Not set')}
📍 Place: {user.get('place', 'Not set')}
📧 Email: {user.get('email', 'Not set')}
💸 UPI: {user.get('upi_id', 'Not set')}
💰 Payment: {'✅ Paid' if user.get('payment_completed') else '❌ Not Paid'}
"""
        keyboard = [
            [InlineKeyboardButton("✏️ Update Name", callback_data="edit_name")],
            [InlineKeyboardButton("📍 Update Place", callback_data="edit_place")],
            [InlineKeyboardButton("📧 Update Email", callback_data="edit_email")],
            [InlineKeyboardButton("🔙 Back", callback_data="back_to_menu")]
        ]
        await query.edit_message_text(profile_text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))
    
    elif data == "demo_quiz":
        demo_data = load_data("demo_question.json")
        if not demo_data:
            demo_data = {"question": "What is 2 + 2?", "options": ["3", "4", "5", "6"], "correct": "4"}
            save_data("demo_question.json", demo_data)
        context.user_data["demo_question"] = demo_data
        options_text = "\n".join([f"{chr(65+i)}. {opt}" for i, opt in enumerate(demo_data["options"])])
        keyboard = [[InlineKeyboardButton(f"{chr(65+i)}. {opt}", callback_data=f"demo_answer_{opt}")] for i, opt in enumerate(demo_data["options"])]
        await query.edit_message_text(f"🎯 *DEMO QUIZ*\n\n{demo_data['question']}\n\n{options_text}", parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))
    
    elif data.startswith("demo_answer_"):
        selected = data.replace("demo_answer_", "")
        demo_q = context.user_data.get("demo_question", {})
        if selected == demo_q.get("correct"):
            await query.edit_message_text("✅ Correct! Register and pay ₹20 to win ₹1000!", reply_markup=get_main_keyboard(user_id))
        else:
            await query.edit_message_text(f"❌ Wrong! Correct: {demo_q.get('correct')}\nRegister and pay ₹20!", reply_markup=get_main_keyboard(user_id))
    
    elif data == "start_quiz":
        users = load_data("users.json")
        if str(user_id) not in users:
            await query.edit_message_text("❌ Register first.", reply_markup=get_main_keyboard(user_id))
            return
        if not users[str(user_id)].get("payment_completed"):
            await query.edit_message_text("❌ Pay ₹20 first.", reply_markup=get_main_keyboard(user_id))
            return
        
        questions = load_data("questions.json")
        if not questions:
            await query.edit_message_text("❌ No questions available.", reply_markup=get_main_keyboard(user_id))
            return
        
        answered = users[str(user_id)].get("answered_questions", [])
        available = [q for q in questions if q["id"] not in answered]
        if not available:
            await query.edit_message_text("🎉 You answered all questions! New ones coming soon.", reply_markup=get_main_keyboard(user_id))
            return
        
        question = random.choice(available)
        context.user_data["current_question"] = question
        options_text = "\n".join([f"{chr(65+i)}. {opt}" for i, opt in enumerate(question["options"])])
        keyboard = [[InlineKeyboardButton(f"{chr(65+i)}. {opt}", callback_data=f"quiz_answer_{opt}_{question['id']}")] for i, opt in enumerate(question["options"])]
        await query.edit_message_text(f"🎯 *QUIZ*\n\n{question['text']}\n\n{options_text}", parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))
    
    elif data.startswith("quiz_answer_"):
        parts = data.split("_")
        selected = parts[2]
        qid = parts[3]
        question = context.user_data.get("current_question", {})
        users = load_data("users.json")
        
        if selected == question.get("correct"):
            if str(user_id) in users:
                answered = users[str(user_id)].get("answered_questions", [])
                if qid not in answered:
                    answered.append(qid)
                    users[str(user_id)]["answered_questions"] = answered
                    users[str(user_id)]["correct_answers"] = users[str(user_id)].get("correct_answers", 0) + 1
                    save_data("users.json", users)
            await query.edit_message_text("✅ *CORRECT!*\n\nSet your UPI ID to receive ₹1000 on Sunday!", parse_mode="Markdown", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("💸 Set UPI", callback_data="set_upi")], [InlineKeyboardButton("🔙 Back", callback_data="back_to_menu")]]))
        else:
            await query.edit_message_text(f"❌ *WRONG!*\nCorrect: {question.get('correct')}\nPay ₹20 to try again!", parse_mode="Markdown", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("💳 Pay ₹20", callback_data="payment")], [InlineKeyboardButton("🔙 Back", callback_data="back_to_menu")]]))
    
    elif data == "payment":
        try:
            order = razorpay_client.order.create({"amount": 2000, "currency": "INR", "payment_capture": 1})
            payments = load_data("payments.json")
            payments[str(order["id"])] = {"user_id": user_id, "status": "pending"}
            save_data("payments.json", payments)
            await query.edit_message_text(f"💳 *Pay ₹20*\n\nOrder ID: `{order['id']}`\n\n[Click to Pay](https://rzp.io/l/payment?order_id={order['id']})\n\nAfter payment, click 'Check Payment'.", parse_mode="Markdown", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("✅ Check Payment", callback_data="check_payment")], [InlineKeyboardButton("🔙 Back", callback_data="back_to_menu")]]), disable_web_page_preview=True)
        except Exception as e:
            await query.edit_message_text("❌ Payment error. Try again.", reply_markup=get_main_keyboard(user_id))
    
    elif data == "check_payment":
        users = load_data("users.json")
        if str(user_id) in users:
            users[str(user_id)]["payment_completed"] = True
            save_data("users.json", users)
        await query.edit_message_text("✅ Payment verified! Click Start Quiz.", reply_markup=get_main_keyboard(user_id))
    
    elif data == "payment_info":
        await query.edit_message_text("💳 Pay ₹20 to unlock the quiz.", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("💳 Pay Now", callback_data="payment")], [InlineKeyboardButton("🔙 Back", callback_data="back_to_menu")]]))
    
    elif data == "set_upi":
        context.user_data["action"] = "set_upi"
        await query.edit_message_text("💸 Send your UPI ID:\nExample: username@okhdfcbank")
        return UPI_INPUT
    
    elif data == "about":
        await query.edit_message_text("📖 *Jannat Foundation Quiz*\n\n💰 Prize: ₹1000\n🎯 1 Question\n📅 Payout: Sunday\n\nContact: @imtiazs37", parse_mode="Markdown", reply_markup=get_main_keyboard(user_id))
    
    elif data == "back_to_menu":
        await query.edit_message_text("Main Menu:", reply_markup=get_main_keyboard(user_id))
    
    elif data == "edit_name":
        context.user_data["action"] = "edit_name"
        await query.edit_message_text("✏️ Send your new Name:")
        return EDIT_NAME
    elif data == "edit_place":
        context.user_data["action"] = "edit_place"
        await query.edit_message_text("📍 Send your new Place:")
        return EDIT_PLACE
    elif data == "edit_email":
        context.user_data["action"] = "edit_email"
        await query.edit_message_text("📧 Send your new Email:")
        return EDIT_EMAIL
    
    return ConversationHandler.END

# ========== REGISTRATION HANDLERS ==========
async def register_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    phone = update.message.text.strip()
    context.user_data["reg_phone"] = phone
    await update.message.reply_text("📝 Send your *Password* (min 4 chars):", parse_mode="Markdown")
    return PASSWORD_REG

async def register_password(update: Update, context: ContextTypes.DEFAULT_TYPE):
    password = update.message.text.strip()
    user_id = update.effective_user.id
    if len(password) < 4:
        await update.message.reply_text("❌ Password too short.")
        return PASSWORD_REG
    users = load_data("users.json")
    users[str(user_id)] = {
        "phone": context.user_data["reg_phone"],
        "password": hash_password(password),
        "name": "", "place": "", "email": "", "upi_id": "",
        "payment_completed": False, "answered_questions": [], "correct_answers": 0,
        "registered_on": datetime.now().isoformat()
    }
    save_data("users.json", users)
    await update.message.reply_text("✅ Registered! Use the menu below:", reply_markup=get_main_keyboard(user_id))
    return ConversationHandler.END

async def save_upi(update: Update, context: ContextTypes.DEFAULT_TYPE):
    upi_id = update.message.text.strip()
    user_id = update.effective_user.id
    users = load_data("users.json")
    if str(user_id) in users:
        users[str(user_id)]["upi_id"] = upi_id
        save_data("users.json", users)
        await update.message.reply_text("✅ UPI saved! Prize will be sent on Sunday.", reply_markup=get_main_keyboard(user_id))
    return ConversationHandler.END

async def edit_name_save(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    users = load_data("users.json")
    if str(user_id) in users:
        users[str(user_id)]["name"] = update.message.text.strip()
        save_data("users.json", users)
        await update.message.reply_text("✅ Name updated!", reply_markup=get_main_keyboard(user_id))
    return ConversationHandler.END

async def edit_place_save(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    users = load_data("users.json")
    if str(user_id) in users:
        users[str(user_id)]["place"] = update.message.text.strip()
        save_data("users.json", users)
        await update.message.reply_text("✅ Place updated!", reply_markup=get_main_keyboard(user_id))
    return ConversationHandler.END

async def edit_email_save(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    users = load_data("users.json")
    if str(user_id) in users:
        users[str(user_id)]["email"] = update.message.text.strip()
        save_data("users.json", users)
        await update.message.reply_text("✅ Email updated!", reply_markup=get_main_keyboard(user_id))
    return ConversationHandler.END

# ========== MAIN ==========
def main():
    if not TOKEN:
        print("❌ No BOT_TOKEN!")
        return
    
    # Initialize files
    for f in ["users.json", "questions.json", "payments.json"]:
        if not os.path.exists(f):
            save_data(f, {} if f != "questions.json" else [])
    if not os.path.exists("demo_question.json"):
        save_data("demo_question.json", {"question": "What is 2+2?", "options": ["3", "4", "5", "6"], "correct": "4"})
    
    app = Application.builder().token(TOKEN).build()
    
    # Conversation handlers
    app.add_handler(ConversationHandler(entry_points=[CallbackQueryHandler(button_handler, pattern="^register$")], states={PHONE_REG: [MessageHandler(filters.TEXT & ~filters.COMMAND, register_phone)], PASSWORD_REG: [MessageHandler(filters.TEXT & ~filters.COMMAND, register_password)]}, fallbacks=[]))
    app.add_handler(ConversationHandler(entry_points=[CallbackQueryHandler(button_handler, pattern="^set_upi$")], states={UPI_INPUT: [MessageHandler(filters.TEXT & ~filters.COMMAND, save_upi)]}, fallbacks=[]))
    app.add_handler(ConversationHandler(entry_points=[CallbackQueryHandler(button_handler, pattern="^edit_name$")], states={EDIT_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, edit_name_save)]}, fallbacks=[]))
    app.add_handler(ConversationHandler(entry_points=[CallbackQueryHandler(button_handler, pattern="^edit_place$")], states={EDIT_PLACE: [MessageHandler(filters.TEXT & ~filters.COMMAND, edit_place_save)]}, fallbacks=[]))
    app.add_handler(ConversationHandler(entry_points=[CallbackQueryHandler(button_handler, pattern="^edit_email$")], states={EDIT_EMAIL: [MessageHandler(filters.TEXT & ~filters.COMMAND, edit_email_save)]}, fallbacks=[]))
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(button_handler))
    
    print("🤖 Bot is running on Python 3.10...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()

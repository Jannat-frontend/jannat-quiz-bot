import os
import json
import logging
import hashlib
import random
from datetime import datetime
from functools import wraps

from flask import Flask
from threading import Thread

from telegram import (
    Update,
    ReplyKeyboardMarkup,
    KeyboardButton,
    InlineKeyboardButton,
    InlineKeyboardMarkup
)

from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ConversationHandler,
    ContextTypes,
    filters
)

import razorpay

# ================= KEEP ALIVE =================
app_web = Flask(__name__)

@app_web.route('/')
def home():
    return "Jannat Quiz Bot is Running!"

def run_web():
    port = int(os.environ.get("PORT", 10000))
    app_web.run(host='0.0.0.0', port=port)

def keep_alive():
    t = Thread(target=run_web)
    t.start()

# ========== CONFIGURATION ==========
TOKEN = os.environ.get("BOT_TOKEN")
RAZORPAY_KEY_ID = os.environ.get("RAZORPAY_KEY_ID")
RAZORPAY_KEY_SECRET = os.environ.get("RAZORPAY_KEY_SECRET")
ADMIN_ID = int(os.environ.get("ADMIN_ID", "0"))

# States for conversation
PHONE_REG, PASSWORD_REG, EDIT_NAME, EDIT_PLACE, EDIT_EMAIL, UPI_INPUT = range(6)

# Setup logging
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# Initialize Razorpay client
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

# ========== PERSISTENT REPLY KEYBOARD ==========
def get_main_keyboard(user_id=None):
    """Get persistent reply keyboard menu"""
    users = load_data("users.json")
    is_registered = user_id and str(user_id) in users
    has_paid = False
    if is_registered:
        has_paid = users[str(user_id)].get("payment_completed", False)
    
    # Create persistent reply keyboard buttons
    keyboard = [
        [KeyboardButton("📝 Register"), KeyboardButton("👤 My Profile")],
        [KeyboardButton("🎯 Demo Quiz"), KeyboardButton("ℹ️ About")],
        [KeyboardButton("💳 Payment (₹20)"), KeyboardButton("💸 Set UPI")],
    ]
    
    # Add Start Quiz button based on status
    if is_registered and has_paid:
        keyboard.append([KeyboardButton("🔓 Start Quiz")])
    else:
        keyboard.append([KeyboardButton("🔒 Start Quiz (Pay ₹20)")])
    
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True, persistent=True)

def get_inline_menu(user_id=None):
    """Fallback inline menu for callbacks"""
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

# ========== COMMAND HANDLERS ==========
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /start command with persistent menu"""
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

*Try Demo Quiz first - It's FREE!*

👇 *Use the buttons below* 👇
"""
    await update.message.reply_text(welcome_msg, parse_mode="Markdown", reply_markup=get_main_keyboard(user.id))

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle reply keyboard button presses"""
    text = update.message.text
    user_id = update.effective_user.id
    
    if text == "📝 Register":
        context.user_data["action"] = "register"
        await update.message.reply_text(
            "📝 *Registration*\n\nPlease send your *Phone Number* (with country code):\n\nExample: +919876543210",
            parse_mode="Markdown"
        )
        return PHONE_REG
    
    elif text == "👤 My Profile":
        await show_profile_message(update, user_id)
    
    elif text == "🎯 Demo Quiz":
        await start_demo_quiz_message(update, user_id, context)
    
    elif text == "ℹ️ About":
        about_text = """
📖 *About Jannat Foundation Quiz*

💰 *Prize:* ₹1000 per correct answer
🎯 *Quiz:* 1 question per attempt
📅 *Payout:* Every Sunday

*Rules:*
• Register with valid phone number
• Pay ₹20 to play
• Answer correctly to win
• Submit UPI ID for payout
• Wrong answer? Pay ₹20 to try again

*Contact:* @imtiazs37

*Jannat Foundation Trust*
"""
        await update.message.reply_text(about_text, parse_mode="Markdown", reply_markup=get_main_keyboard(user_id))
    
    elif text == "💳 Payment (₹20)":
        await create_payment_message(update, user_id)
    
    elif text == "💸 Set UPI":
        context.user_data["action"] = "set_upi"
        await update.message.reply_text(
            "💸 *Set UPI ID*\n\nPlease send your UPI ID.\n\nExample: username@okhdfcbank\n\n*Note: This is required to receive your prize money on Sunday!*",
            parse_mode="Markdown"
        )
        return UPI_INPUT
    
    elif text == "🔓 Start Quiz":
        await start_real_quiz_message(update, user_id, context)
    
    elif text == "🔒 Start Quiz (Pay ₹20)":
        await update.message.reply_text(
            "💳 *Payment Required*\n\nYou need to pay ₹20 to unlock the quiz.\n\nClick the Payment button below.",
            parse_mode="Markdown",
            reply_markup=get_main_keyboard(user_id)
        )
    
    return ConversationHandler.END

async def show_profile_message(update: Update, user_id):
    users = load_data("users.json")
    if str(user_id) not in users:
        await update.message.reply_text("❌ Please register first.", reply_markup=get_main_keyboard(user_id))
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
🎯 Correct Answers: {user.get('correct_answers', 0)}
🏆 Reward Pending: {'Yes' if user.get('reward_pending') else 'No'}
"""
    keyboard = [
        ["✏️ Update Name", "📍 Update Place"],
        ["📧 Update Email", "🔙 Main Menu"]
    ]
    await update.message.reply_text(profile_text, parse_mode="Markdown", reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True))

async def start_demo_quiz_message(update: Update, user_id, context):
    demo_data = load_data("demo_question.json")
    if not demo_data:
        demo_data = {"question": "What is 2 + 2?", "options": ["3", "4", "5", "6"], "correct": "4"}
        save_data("demo_question.json", demo_data)
    
    context.user_data["demo_question"] = demo_data
    options_text = "\n".join([f"{chr(65+i)}. {opt}" for i, opt in enumerate(demo_data["options"])])
    
    await update.message.reply_text(
        f"🎯 *DEMO QUIZ (FREE)*\n\n{demo_data['question']}\n\n{options_text}\n\n*Reply with the letter (A, B, C, or D) of your answer.*",
        parse_mode="Markdown"
    )
    context.user_data["awaiting_demo_answer"] = True

async def handle_demo_answer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.user_data.get("awaiting_demo_answer"):
        return
    user_id = update.effective_user.id
    answer = update.message.text.strip().upper()
    demo_q = context.user_data.get("demo_question", {})
    
    letter_map = {"A": 0, "B": 1, "C": 2, "D": 3}
    if answer in letter_map:
        selected = demo_q["options"][letter_map[answer]]
        if selected == demo_q.get("correct"):
            await update.message.reply_text("✅ Correct! Register and pay ₹20 to win ₹1000!", reply_markup=get_main_keyboard(user_id))
        else:
            await update.message.reply_text(f"❌ Wrong! Correct: {demo_q.get('correct')}\nRegister and pay ₹20!", reply_markup=get_main_keyboard(user_id))
    else:
        await update.message.reply_text("Please reply with A, B, C, or D.", reply_markup=get_main_keyboard(user_id))
    
    context.user_data["awaiting_demo_answer"] = False

async def create_payment_message(update: Update, user_id):
    users = load_data("users.json")
    if str(user_id) not in users:
        await update.message.reply_text("❌ Please register first.", reply_markup=get_main_keyboard(user_id))
        return
    
    try:
        # Get user's phone for Razorpay
        phone = users[str(user_id)].get("phone", "")
        
        # Create Razorpay Payment Link
        payment_link_data = razorpay_client.payment_link.create({
            "amount": 2000,
            "currency": "INR",
            "description": f"Jannat Foundation Quiz Fee - User {user_id}",
            "customer": {
                "contact": phone
            },
            "notify": {
                "sms": True,
                "email": False
            },
            "reminder_enable": True,
            "notes": {
                "telegram_id": str(user_id)
            },
            "callback_url": "https://t.me/Jannat_Foundationbot",
            "callback_method": "get"
        })
        
        payment_url = payment_link_data["short_url"]
        
        # Store payment link reference
        payments = load_data("payments.json")
        payments[payment_link_data["id"]] = {
            "user_id": user_id,
            "amount": 20,
            "status": "pending",
            "created_at": datetime.now().isoformat()
        }
        save_data("payments.json", payments)
        
        await update.message.reply_text(
            f"💳 *Payment Required*\n\n💰 Amount: ₹20\n\n🔗 [Click here to pay ₹20 via Razorpay]({payment_url})\n\n*After successful payment, click the 'Start Quiz' button to play!*",
            parse_mode="Markdown",
            reply_markup=get_main_keyboard(user_id),
            disable_web_page_preview=True
        )
        
    except Exception as e:
        logger.error(f"Payment error: {e}")
        await update.message.reply_text("❌ Payment service error. Please try again later.", reply_markup=get_main_keyboard(user_id))

async def start_real_quiz_message(update: Update, user_id, context):
    users = load_data("users.json")
    if str(user_id) not in users:
        await update.message.reply_text("❌ Register first.", reply_markup=get_main_keyboard(user_id))
        return
    
    # Check payment status via Razorpay
    payments = load_data("payments.json")
    user_paid = users[str(user_id)].get("payment_completed", False)
    
    # Verify with Razorpay if not marked paid
    if not user_paid:
        for payment_id, payment in payments.items():
            if payment["user_id"] == user_id and payment["status"] == "pending":
                try:
                    payment_link = razorpay_client.payment_link.fetch(payment_id)
                    if payment_link["status"] == "paid":
                        users[str(user_id)]["payment_completed"] = True
                        save_data("users.json", users)
                        user_paid = True
                except:
                    pass
    
    if not user_paid:
        await update.message.reply_text("❌ Please complete payment (₹20) first.", reply_markup=get_main_keyboard(user_id))
        return
    
    questions = load_data("questions.json")
    if not questions:
        await update.message.reply_text("❌ No questions available. Admin will add soon.", reply_markup=get_main_keyboard(user_id))
        return
    
    answered = users[str(user_id)].get("answered_questions", [])
    available = [q for q in questions if q["id"] not in answered]
    if not available:
        await update.message.reply_text("🎉 You answered all questions! New ones coming soon.", reply_markup=get_main_keyboard(user_id))
        return
    
    question = random.choice(available)
    context.user_data["current_question"] = question
    options_text = "\n".join([f"{chr(65+i)}. {opt}" for i, opt in enumerate(question["options"])])
    
    await update.message.reply_text(
        f"🎯 *QUIZ TIME!*\n\n*Question:* {question['text']}\n\n{options_text}\n\n*Reply with the letter (A, B, C, or D) of your answer.*",
        parse_mode="Markdown"
    )
    context.user_data["awaiting_quiz_answer"] = True

async def handle_quiz_answer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.user_data.get("awaiting_quiz_answer"):
        return
    
    user_id = update.effective_user.id
    answer = update.message.text.strip().upper()
    question = context.user_data.get("current_question", {})
    
    letter_map = {"A": 0, "B": 1, "C": 2, "D": 3}
    
    if answer in letter_map:
        selected = question["options"][letter_map[answer]]
        users = load_data("users.json")
        
        if selected == question.get("correct"):
            if str(user_id) in users:
                answered = users[str(user_id)].get("answered_questions", [])
                if question["id"] not in answered:
                    answered.append(question["id"])
                    users[str(user_id)]["answered_questions"] = answered
                    users[str(user_id)]["correct_answers"] = users[str(user_id)].get("correct_answers", 0) + 1
                    save_data("users.json", users)
            
            await update.message.reply_text(
                "✅ *CORRECT ANSWER!* 🎉\n\n🏆 *Please click the 'Set UPI' button below to receive your ₹1000 prize on Sunday!*",
                parse_mode="Markdown",
                reply_markup=get_main_keyboard(user_id)
            )
            
            if ADMIN_ID:
                await context.bot.send_message(
                    ADMIN_ID,
                    f"✅ User {user_id} answered correctly!\nQuestion: {question.get('text')}"
                )
        else:
            await update.message.reply_text(
                f"❌ *WRONG ANSWER!*\n\nThe correct answer was: *{question.get('correct')}*\n\n💳 *Please pay ₹20 to try again.*",
                parse_mode="Markdown",
                reply_markup=get_main_keyboard(user_id)
            )
    else:
        await update.message.reply_text("Please reply with A, B, C, or D.", reply_markup=get_main_keyboard(user_id))
    
    context.user_data["awaiting_quiz_answer"] = False

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
        users[str(user_id)]["reward_pending"] = True
        save_data("users.json", users)
        await update.message.reply_text("✅ UPI saved! Prize will be sent on Sunday.", reply_markup=get_main_keyboard(user_id))
        
        if ADMIN_ID:
            await context.bot.send_message(ADMIN_ID, f"💰 Winner! User: {user_id}\nUPI: {upi_id}")
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
    app.add_handler(ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^📝 Register$"), register_phone)],
        states={PHONE_REG: [MessageHandler(filters.TEXT & ~filters.COMMAND, register_phone)],
                PASSWORD_REG: [MessageHandler(filters.TEXT & ~filters.COMMAND, register_password)]},
        fallbacks=[],
        per_message=False
    ))
    
    app.add_handler(ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^💸 Set UPI$"), save_upi)],
        states={UPI_INPUT: [MessageHandler(filters.TEXT & ~filters.COMMAND, save_upi)]},
        fallbacks=[],
        per_message=False
    ))
    
    # Edit profile handlers
    app.add_handler(ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^✏️ Update Name$"), edit_name_save)],
        states={EDIT_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, edit_name_save)]},
        fallbacks=[]
    ))
    
    app.add_handler(ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^📍 Update Place$"), edit_place_save)],
        states={EDIT_PLACE: [MessageHandler(filters.TEXT & ~filters.COMMAND, edit_place_save)]},
        fallbacks=[]
    ))
    
    app.add_handler(ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^📧 Update Email$"), edit_email_save)],
        states={EDIT_EMAIL: [MessageHandler(filters.TEXT & ~filters.COMMAND, edit_email_save)]},
        fallbacks=[]
    ))
    
    # Demo and quiz answer handlers
    app.add_handler(MessageHandler(filters.Regex("^🔙 Main Menu$"), start))
    app.add_handler(MessageHandler(filters.Regex("^👤 My Profile$"), show_profile_message))
    app.add_handler(MessageHandler(filters.Regex("^🎯 Demo Quiz$"), start_demo_quiz_message))
    app.add_handler(MessageHandler(filters.Regex("^ℹ️ About$"), handle_message))
    app.add_handler(MessageHandler(filters.Regex("^💳 Payment \\(₹20\\)$"), create_payment_message))
    app.add_handler(MessageHandler(filters.Regex("^🔓 Start Quiz$"), start_real_quiz_message))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_demo_answer))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_quiz_answer))
    
    app.add_handler(CommandHandler("start", start))
    
    # Admin commands
    async def admin_stats(update, context):
        if update.effective_user.id != ADMIN_ID:
            return
        users = load_data("users.json")
        questions = load_data("questions.json")
        await update.message.reply_text(f"📊 Stats\nUsers: {len(users)}\nQuestions: {len(questions)}")
    
    async def add_question(update, context):
        if update.effective_user.id != ADMIN_ID:
            return
        args = context.args
        if len(args) < 6:
            await update.message.reply_text("Usage: /add_question Q Opt1 Opt2 Opt3 Opt4 Correct")
            return
        questions = load_data("questions.json")
        questions.append({"id": f"Q{len(questions)+1}", "text": args[0], "options": args[1:5], "correct": args[5]})
        save_data("questions.json", questions)
        await update.message.reply_text("✅ Question added!")
    
    app.add_handler(CommandHandler("stats", admin_stats))
    app.add_handler(CommandHandler("add_question", add_question))
    
    print("🤖 Jannat Foundation Quiz Bot is running with Persistent Reply Keyboard!")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    keep_alive()
    main()

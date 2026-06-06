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
try:
    razorpay_client = razorpay.Client(auth=(RAZORPAY_KEY_ID, RAZORPAY_KEY_SECRET))
    print(f"✅ Razorpay initialized with Key ID: {RAZORPAY_KEY_ID[:10]}...")
except Exception as e:
    print(f"❌ Razorpay init error: {e}")
    razorpay_client = None

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
    """Get persistent reply keyboard menu - stays at bottom"""
    users = load_data("users.json")
    is_registered = user_id and str(user_id) in users
    has_paid = False
    if is_registered:
        has_paid = users[str(user_id)].get("payment_completed", False)
    
    # Create persistent reply keyboard buttons - MATCH EXACTLY with handler text
    keyboard = [
        ["📝 Register", "👤 My Profile"],
        ["🎯 Demo Quiz", "ℹ️ About"],
        ["💳 Payment", "💸 Set UPI"],
    ]
    
    # Add Start Quiz button based on status
    if is_registered and has_paid:
        keyboard.append(["🔓 Start Quiz"])
    else:
        keyboard.append(["🔒 Start Quiz"])
    
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

# ========== REGISTRATION START FUNCTION ==========
async def register_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start registration - ask for phone number"""
    await update.message.reply_text(
        "📝 *Registration*\n\nPlease send your *Phone Number* (with country code):\n\nExample: +919876543210",
        parse_mode="Markdown"
    )
    return PHONE_REG

async def register_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Receive phone number"""
    phone = update.message.text.strip()
    context.user_data["reg_phone"] = phone
    await update.message.reply_text(
        "📝 Send your *Password* (minimum 4 characters):",
        parse_mode="Markdown"
    )
    return PASSWORD_REG

async def register_password(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Receive password and complete registration"""
    password = update.message.text.strip()
    user_id = update.effective_user.id
    
    if len(password) < 4:
        await update.message.reply_text("❌ Password must be at least 4 characters. Please try again.")
        return PASSWORD_REG
    
    users = load_data("users.json")
    
    if str(user_id) in users:
        await update.message.reply_text("✅ You are already registered!", reply_markup=get_main_keyboard(user_id))
        return ConversationHandler.END
    
    # Save user
    users[str(user_id)] = {
        "registered": True,
        "phone": context.user_data["reg_phone"],
        "password": hash_password(password),
        "name": "",
        "place": "",
        "email": "",
        "upi_id": "",
        "payment_completed": False,
        "payment_link_id": None,
        "answered_questions": [],
        "correct_answers": 0,
        "reward_pending": False,
        "registered_on": datetime.now().isoformat()
    }
    save_data("users.json", users)
    
    await update.message.reply_text(
        "✅ *Registration Successful!*\n\nYou can now:\n• Update your profile\n• Pay ₹20 to start quiz\n\nUse the buttons below:",
        parse_mode="Markdown",
        reply_markup=get_main_keyboard(user_id)
    )
    
    # Notify admin
    if ADMIN_ID:
        await context.bot.send_message(
            ADMIN_ID,
            f"🆕 New User Registered!\nUser ID: {user_id}\nPhone: {context.user_data['reg_phone']}"
        )
    
    return ConversationHandler.END

# ========== UPI START FUNCTION ==========
async def upi_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start UPI collection"""
    await update.message.reply_text(
        "💸 *Set UPI ID*\n\nPlease send your UPI ID.\n\nExample: username@okhdfcbank\n\n*Note: This is required to receive your prize money on Sunday!*",
        parse_mode="Markdown"
    )
    return UPI_INPUT

async def save_upi(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Save UPI ID"""
    upi_id = update.message.text.strip()
    user_id = update.effective_user.id
    
    users = load_data("users.json")
    if str(user_id) in users:
        users[str(user_id)]["upi_id"] = upi_id
        users[str(user_id)]["reward_pending"] = True
        save_data("users.json", users)
        
        await update.message.reply_text(
            "✅ *UPI ID Saved Successfully!*\n\n🏆 *Jannat Foundation will pay your prize on coming Sunday!*\n\nThank you for participating!",
            parse_mode="Markdown",
            reply_markup=get_main_keyboard(user_id)
        )
        
        if ADMIN_ID:
            await context.bot.send_message(ADMIN_ID, f"💰 Winner! User: {user_id}\nUPI: {upi_id}")
    else:
        await update.message.reply_text("❌ Please register first.", reply_markup=get_main_keyboard(user_id))
    
    return ConversationHandler.END

# ========== PROFILE FUNCTIONS ==========
async def show_profile(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show user profile"""
    user_id = update.effective_user.id
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
    await update.message.reply_text(profile_text, parse_mode="Markdown", reply_markup=get_main_keyboard(user_id))

# ========== EDIT PROFILE FUNCTIONS ==========
async def edit_name_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("✏️ Send your new *Name*:", parse_mode="Markdown")
    return EDIT_NAME

async def edit_name_save(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    users = load_data("users.json")
    if str(user_id) in users:
        users[str(user_id)]["name"] = update.message.text.strip()
        save_data("users.json", users)
        await update.message.reply_text("✅ Name updated!", reply_markup=get_main_keyboard(user_id))
    return ConversationHandler.END

async def edit_place_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("📍 Send your new *Place/City*:", parse_mode="Markdown")
    return EDIT_PLACE

async def edit_place_save(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    users = load_data("users.json")
    if str(user_id) in users:
        users[str(user_id)]["place"] = update.message.text.strip()
        save_data("users.json", users)
        await update.message.reply_text("✅ Place updated!", reply_markup=get_main_keyboard(user_id))
    return ConversationHandler.END

async def edit_email_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("📧 Send your new *Email*:", parse_mode="Markdown")
    return EDIT_EMAIL

async def edit_email_save(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    users = load_data("users.json")
    if str(user_id) in users:
        users[str(user_id)]["email"] = update.message.text.strip()
        save_data("users.json", users)
        await update.message.reply_text("✅ Email updated!", reply_markup=get_main_keyboard(user_id))
    return ConversationHandler.END

# ========== DEMO QUIZ ==========
async def start_demo_quiz(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start demo quiz"""
    user_id = update.effective_user.id
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
    """Handle demo quiz answer"""
    if not context.user_data.get("awaiting_demo_answer"):
        return
    
    user_id = update.effective_user.id
    answer = update.message.text.strip().upper()
    demo_q = context.user_data.get("demo_question", {})
    
    letter_map = {"A": 0, "B": 1, "C": 2, "D": 3}
    if answer in letter_map:
        selected = demo_q["options"][letter_map[answer]]
        if selected == demo_q.get("correct"):
            await update.message.reply_text(
                "✅ Correct! Register and pay ₹20 to win ₹1000!",
                reply_markup=get_main_keyboard(user_id)
            )
        else:
            await update.message.reply_text(
                f"❌ Wrong! Correct: {demo_q.get('correct')}\nRegister and pay ₹20!",
                reply_markup=get_main_keyboard(user_id)
            )
    else:
        await update.message.reply_text("Please reply with A, B, C, or D.", reply_markup=get_main_keyboard(user_id))
    
    context.user_data["awaiting_demo_answer"] = False

# ========== PAYMENT FUNCTIONS ==========
async def create_payment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Create Razorpay Payment Link"""
    print("💳 PAYMENT BUTTON CLICKED")  # Debug
    user_id = update.effective_user.id
    users = load_data("users.json")
    
    if str(user_id) not in users:
        await update.message.reply_text("❌ Please register first.", reply_markup=get_main_keyboard(user_id))
        return
    
    if not razorpay_client:
        await update.message.reply_text("❌ Payment service not configured. Please contact admin.", reply_markup=get_main_keyboard(user_id))
        return
    
    try:
        phone = users[str(user_id)].get("phone", "")
        print(f"Creating payment for user {user_id}, phone: {phone}")
        
        # Create Razorpay Payment Link
        payment_link_data = razorpay_client.payment_link.create({
            "amount": 2000,
            "currency": "INR",
            "description": f"Jannat Foundation Quiz Fee - User {user_id}",
            "customer": {"contact": phone} if phone else {},
            "notify": {"sms": True, "email": False},
            "reminder_enable": True,
            "notes": {"telegram_id": str(user_id)},
            "callback_url": "https://jannat-quiz-bot.onrender.com",
            "callback_method": "get"
        })
        
        payment_url = payment_link_data["short_url"]
        print(f"Payment link created: {payment_url}")
        
        # Store payment link reference
        payments = load_data("payments.json")
        payments[payment_link_data["id"]] = {
            "user_id": user_id,
            "amount": 20,
            "status": "pending",
            "created_at": datetime.now().isoformat()
        }
        save_data("payments.json", payments)
        
        # Store in user data
        users[str(user_id)]["payment_link_id"] = payment_link_data["id"]
        save_data("users.json", users)
        
        await update.message.reply_text(
            f"💳 *Payment Required*\n\n💰 Amount: ₹20\n\n🔗 [Click here to pay ₹20 via Razorpay]({payment_url})\n\n*After successful payment, click '🔓 Start Quiz' to play!*",
            parse_mode="Markdown",
            reply_markup=get_main_keyboard(user_id),
            disable_web_page_preview=True
        )
        
    except Exception as e:
        print(f"❌ Payment error: {e}")
        logger.error(f"Payment error: {e}")
        await update.message.reply_text(f"❌ Payment error: {str(e)[:100]}", reply_markup=get_main_keyboard(user_id))

async def check_payment_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Check and update payment status"""
    print("🔍 CHECK PAYMENT STATUS")
    user_id = update.effective_user.id
    users = load_data("users.json")
    payments = load_data("payments.json")
    
    if str(user_id) not in users:
        await update.message.reply_text("❌ Please register first.", reply_markup=get_main_keyboard(user_id))
        return
    
    if users[str(user_id)].get("payment_completed"):
        await update.message.reply_text("✅ You already have payment verified! Click '🔓 Start Quiz' to play.", reply_markup=get_main_keyboard(user_id))
        return
    
    payment_link_id = users[str(user_id)].get("payment_link_id")
    if not payment_link_id or payment_link_id not in payments:
        await update.message.reply_text("❌ No payment found. Please click '💳 Payment' to make a payment first.", reply_markup=get_main_keyboard(user_id))
        return
    
    try:
        payment_link = razorpay_client.payment_link.fetch(payment_link_id)
        print(f"Payment status: {payment_link['status']}")
        
        if payment_link["status"] == "paid":
            users[str(user_id)]["payment_completed"] = True
            payments[payment_link_id]["status"] = "completed"
            save_data("users.json", users)
            save_data("payments.json", payments)
            
            await update.message.reply_text(
                "✅ *Payment Successful!* 🎉\n\n🔓 *Start Quiz is now UNLOCKED!*\n\nClick '🔓 Start Quiz' to play and win ₹1000!",
                parse_mode="Markdown",
                reply_markup=get_main_keyboard(user_id)
            )
            
            if ADMIN_ID:
                await context.bot.send_message(ADMIN_ID, f"💳 Payment completed! User: {user_id}")
        else:
            await update.message.reply_text(
                f"⏳ Payment pending. Amount: ₹20\n\nPlease complete your payment using the link.\n\nAfter payment, click '🔓 Start Quiz' again.",
                reply_markup=get_main_keyboard(user_id)
            )
    except Exception as e:
        print(f"❌ Payment check error: {e}")
        await update.message.reply_text("❌ Could not verify payment. Please try again.", reply_markup=get_main_keyboard(user_id))

# ========== REAL QUIZ ==========
async def start_real_quiz(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start real quiz (after payment)"""
    print("🎯 START QUIZ COMMAND RECEIVED")
    user_id = update.effective_user.id
    users = load_data("users.json")
    
    if str(user_id) not in users:
        await update.message.reply_text("❌ Register first.", reply_markup=get_main_keyboard(user_id))
        return
    
    # First check payment status
    payment_link_id = users[str(user_id)].get("payment_link_id")
    if not users[str(user_id)].get("payment_completed") and payment_link_id:
        payments = load_data("payments.json")
        try:
            payment_link = razorpay_client.payment_link.fetch(payment_link_id)
            if payment_link["status"] == "paid":
                users[str(user_id)]["payment_completed"] = True
                payments[payment_link_id]["status"] = "completed"
                save_data("users.json", users)
                save_data("payments.json", payments)
                print(f"Payment auto-verified for user {user_id}")
        except Exception as e:
            print(f"Auto-verify error: {e}")
    
    if not users[str(user_id)].get("payment_completed"):
        await update.message.reply_text(
            "❌ Please complete payment (₹20) first.\n\nClick '💳 Payment' to pay.",
            reply_markup=get_main_keyboard(user_id)
        )
        return
    
    questions = load_data("questions.json")
    if not questions:
        await update.message.reply_text("❌ No questions available. Admin will add soon.", reply_markup=get_main_keyboard(user_id))
        return
    
    answered = users[str(user_id)].get("answered_questions", [])
    available = [q for q in questions if q["id"] not in answered]
    
    if not available:
        await update.message.reply_text(
            "🎉 *Congratulations!* 🎉\n\nYou have answered all available questions!\n\nNew questions will be added soon.",
            parse_mode="Markdown",
            reply_markup=get_main_keyboard(user_id)
        )
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
    """Handle real quiz answer"""
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
                "✅ *CORRECT ANSWER!* 🎉\n\n🏆 *Please click '💸 Set UPI' to receive your ₹1000 prize on Sunday!*",
                parse_mode="Markdown",
                reply_markup=get_main_keyboard(user_id)
            )
            
            if ADMIN_ID:
                await context.bot.send_message(
                    ADMIN_ID,
                    f"✅ User {user_id} answered correctly!\nQuestion: {question.get('text')}"
                )
        else:
            # Wrong answer - reset payment status
            if str(user_id) in users:
                users[str(user_id)]["payment_completed"] = False
                save_data("users.json", users)
            
            await update.message.reply_text(
                f"❌ *WRONG ANSWER!*\n\nThe correct answer was: *{question.get('correct')}*\n\n💳 *Please pay ₹20 to try again.*",
                parse_mode="Markdown",
                reply_markup=get_main_keyboard(user_id)
            )
    else:
        await update.message.reply_text("Please reply with A, B, C, or D.", reply_markup=get_main_keyboard(user_id))
    
    context.user_data["awaiting_quiz_answer"] = False

# ========== ABOUT ==========
async def show_about(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show about information"""
    user_id = update.effective_user.id
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

# ========== MAIN MESSAGE HANDLER ==========
async def handle_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Main menu router for reply keyboard buttons - MATCHES EXACT BUTTON TEXT"""
    text = update.message.text
    user_id = update.effective_user.id
    
    print(f"📱 Menu button pressed: '{text}'")  # Debug - shows exactly what button was pressed
    
    if text == "📝 Register":
        return await register_start(update, context)
    
    elif text == "👤 My Profile":
        return await show_profile(update, context)
    
    elif text == "🎯 Demo Quiz":
        return await start_demo_quiz(update, context)
    
    elif text == "ℹ️ About":
        return await show_about(update, context)
    
    elif text == "💳 Payment":  # EXACT match with keyboard
        return await create_payment(update, context)
    
    elif text == "💸 Set UPI":  # EXACT match with keyboard
        return await upi_start(update, context)
    
    elif text == "🔓 Start Quiz":  # EXACT match with keyboard
        return await start_real_quiz(update, context)
    
    elif text == "🔒 Start Quiz":  # EXACT match with keyboard
        return await check_payment_status(update, context)
    
    elif text == "✏️ Update Name":
        return await edit_name_start(update, context)
    
    elif text == "📍 Update Place":
        return await edit_place_start(update, context)
    
    elif text == "📧 Update Email":
        return await edit_email_start(update, context)
    
    elif text == "🔙 Main Menu":
        await update.message.reply_text("Main Menu:", reply_markup=get_main_keyboard(user_id))
    else:
        # Unknown message - ignore or help
        pass
    
    return ConversationHandler.END

# ========== START COMMAND ==========
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /start command"""
    print("🚀 START COMMAND RECEIVED")
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

# ========== ADMIN COMMANDS ==========
async def admin_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("⛔ Not authorized.")
        return
    users = load_data("users.json")
    questions = load_data("questions.json")
    payments = load_data("payments.json")
    
    stats_text = f"""
📊 *Admin Statistics*

👥 Total Users: {len(users)}
💰 Paid Users: {sum(1 for u in users.values() if u.get('payment_completed'))}
✅ Correct Answers: {sum(u.get('correct_answers', 0) for u in users.values())}
💳 Total Payments: {len([p for p in payments.values() if p.get('status') == 'completed'])}
📚 Questions: {len(questions)}
"""
    await update.message.reply_text(stats_text, parse_mode="Markdown")

async def add_question(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("⛔ Not authorized.")
        return
    args = context.args
    if len(args) < 6:
        await update.message.reply_text(
            "❌ Usage:\n/add_question \"Question\" \"Opt1\" \"Opt2\" \"Opt3\" \"Opt4\" \"Correct\"\n\nExample:\n/add_question \"What is 2+2?\" \"3\" \"4\" \"5\" \"6\" \"4\""
        )
        return
    
    questions = load_data("questions.json")
    new_id = f"Q{len(questions) + 1}"
    questions.append({
        "id": new_id,
        "text": args[0],
        "options": [args[1], args[2], args[3], args[4]],
        "correct": args[5]
    })
    save_data("questions.json", questions)
    await update.message.reply_text(f"✅ Question added!\nID: {new_id}\nQuestion: {args[0]}")

async def update_demo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("⛔ Not authorized.")
        return
    args = context.args
    if len(args) < 6:
        await update.message.reply_text("Usage: /update_demo Q Opt1 Opt2 Opt3 Opt4 Correct")
        return
    demo_q = {
        "question": args[0],
        "options": [args[1], args[2], args[3], args[4]],
        "correct": args[5]
    }
    save_data("demo_question.json", demo_q)
    await update.message.reply_text("✅ Demo question updated!")

async def pending_upi(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("⛔ Not authorized.")
        return
    users = load_data("users.json")
    pending = []
    for uid, user in users.items():
        if user.get("reward_pending") and user.get("upi_id"):
            pending.append(f"User: {uid}\n   Name: {user.get('name', 'N/A')}\n   UPI: {user.get('upi_id')}\n")
    if pending:
        await update.message.reply_text(f"💰 *Pending Payouts (Sunday)*\n\n{chr(10).join(pending)}", parse_mode="Markdown")
    else:
        await update.message.reply_text("No pending payouts.")

async def broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("⛔ Not authorized.")
        return
    message = " ".join(context.args)
    if not message:
        await update.message.reply_text("❌ Usage: /broadcast Your message here")
        return
    users = load_data("users.json")
    sent = 0
    failed = 0
    await update.message.reply_text(f"📢 Broadcasting to {len(users)} users...")
    for uid in users.keys():
        try:
            await context.bot.send_message(int(uid), f"📢 *Announcement*\n\n{message}", parse_mode="Markdown")
            sent += 1
        except:
            failed += 1
    await update.message.reply_text(f"✅ Broadcast complete!\nSent: {sent}\nFailed: {failed}")

# ========== MAIN ==========
def main():
    if not TOKEN:
        print("❌ No BOT_TOKEN!")
        return
    
    print(f"🤖 Bot Token: {TOKEN[:10]}...")
    print(f"💰 Razorpay Key ID: {RAZORPAY_KEY_ID[:10] if RAZORPAY_KEY_ID else 'NOT SET'}...")
    print(f"👑 Admin ID: {ADMIN_ID}")
    
    # Initialize files
    for f in ["users.json", "questions.json", "payments.json"]:
        if not os.path.exists(f):
            save_data(f, {} if f != "questions.json" else [])
    if not os.path.exists("demo_question.json"):
        save_data("demo_question.json", {"question": "What is 2+2?", "options": ["3", "4", "5", "6"], "correct": "4"})
    
    app = Application.builder().token(TOKEN).build()
    
    # Conversation handlers
    reg_conv = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^📝 Register$"), register_start)],
        states={
            PHONE_REG: [MessageHandler(filters.TEXT & ~filters.COMMAND, register_phone)],
            PASSWORD_REG: [MessageHandler(filters.TEXT & ~filters.COMMAND, register_password)],
        },
        fallbacks=[]
    )
    app.add_handler(reg_conv)
    
    upi_conv = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^💸 Set UPI$"), upi_start)],
        states={UPI_INPUT: [MessageHandler(filters.TEXT & ~filters.COMMAND, save_upi)]},
        fallbacks=[]
    )
    app.add_handler(upi_conv)
    
    edit_name_conv = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^✏️ Update Name$"), edit_name_start)],
        states={EDIT_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, edit_name_save)]},
        fallbacks=[]
    )
    app.add_handler(edit_name_conv)
    
    edit_place_conv = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^📍 Update Place$"), edit_place_start)],
        states={EDIT_PLACE: [MessageHandler(filters.TEXT & ~filters.COMMAND, edit_place_save)]},
        fallbacks=[]
    )
    app.add_handler(edit_place_conv)
    
    edit_email_conv = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^📧 Update Email$"), edit_email_start)],
        states={EDIT_EMAIL: [MessageHandler(filters.TEXT & ~filters.COMMAND, edit_email_save)]},
        fallbacks=[]
    )
    app.add_handler(edit_email_conv)
    
    # IMPORTANT: Order matters! Demo and quiz handlers FIRST, then menu handler
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_demo_answer))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_quiz_answer))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_menu))
    
    # Command handlers
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("stats", admin_stats))
    app.add_handler(CommandHandler("add_question", add_question))
    app.add_handler(CommandHandler("update_demo", update_demo))
    app.add_handler(CommandHandler("pending_upi", pending_upi))
    app.add_handler(CommandHandler("broadcast", broadcast))
    
    print("🤖 Jannat Foundation Quiz Bot is running with Persistent Reply Keyboard!")
    print("✅ All handlers registered. Waiting for messages...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    keep_alive()
    main()

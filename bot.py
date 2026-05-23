import os
import json
import logging
import hashlib
import secrets
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
ADMIN_ID = int(os.environ.get("ADMIN_ID", "0"))  # Your numeric Telegram ID

# States for conversation
PHONE_REG, PASSWORD_REG, EDIT_NAME, EDIT_PLACE, EDIT_EMAIL, UPI_INPUT = range(6)

# Setup logging
logging.basicConfig(format='%(asctime)s - %(name)s - %levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# Initialize Razorpay client
razorpay_client = razorpay.Client(auth=(RAZORPAY_KEY_ID, RAZORPAY_KEY_SECRET))

# ========== DATA FILES ==========
DATA_FILES = {
    "users": "users.json",
    "questions": "questions.json",
    "demo": "demo_question.json",
    "payments": "payments.json"
}

def load_data(filename):
    """Load JSON data from file"""
    if os.path.exists(filename):
        with open(filename, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {} if filename != "questions.json" else []

def save_data(filename, data):
    """Save JSON data to file"""
    with open(filename, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

# ========== ADMIN DECORATOR ==========
def admin_only(func):
    @wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
        user_id = update.effective_user.id
        if user_id != ADMIN_ID:
            await update.message.reply_text("⛔ You are not authorized to use this command.")
            return
        return await func(update, context, *args, **kwargs)
    return wrapper

# ========== HELPER FUNCTIONS ==========
def hash_password(password):
    """Hash password using SHA256"""
    return hashlib.sha256(password.encode()).hexdigest()

def verify_password(password, hashed):
    """Verify password"""
    return hash_password(password) == hashed

def get_main_keyboard(user_id=None, user_data=None):
    """Get main menu keyboard based on user status"""
    keyboard = []
    
    # Check if user is registered
    users = load_data("users.json")
    is_registered = user_id and str(user_id) in users
    has_paid = False
    if is_registered:
        has_paid = users[str(user_id)].get("payment_completed", False)
    
    keyboard.append([InlineKeyboardButton("📝 Register", callback_data="register")])
    keyboard.append([InlineKeyboardButton("👤 My Profile", callback_data="profile")])
    keyboard.append([InlineKeyboardButton("🎯 Demo Quiz", callback_data="demo_quiz")])
    
    # Start Quiz button - only if registered AND paid
    if is_registered and has_paid:
        keyboard.append([InlineKeyboardButton("🔓 Start Quiz (Active)", callback_data="start_quiz")])
    else:
        keyboard.append([InlineKeyboardButton("🔒 Start Quiz (Pay ₹20 first)", callback_data="payment_info")])
    
    keyboard.append([InlineKeyboardButton("💳 Payment (₹20)", callback_data="payment")])
    keyboard.append([InlineKeyboardButton("💸 Set UPI ID", callback_data="set_upi")])
    keyboard.append([InlineKeyboardButton("ℹ️ About / Rules", callback_data="about")])
    
    return InlineKeyboardMarkup(keyboard)

# ========== COMMAND HANDLERS ==========
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /start command"""
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

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle all button callbacks"""
    query = update.callback_query
    await query.answer()
    
    data = query.data
    user_id = query.from_user.id
    
    if data == "register":
        context.user_data["action"] = "register"
        await query.edit_message_text(
            "📝 *Registration*\n\nPlease send your *Phone Number* (with country code):\n\nExample: +919876543210",
            parse_mode="Markdown"
        )
        return PHONE_REG
    
    elif data == "profile":
        await show_profile(query, user_id)
    
    elif data == "demo_quiz":
        await start_demo_quiz(query, user_id, context)
    
    elif data == "start_quiz":
        await start_real_quiz(query, user_id, context)
    
    elif data == "payment":
        await create_payment(query, user_id)
    
    elif data == "payment_info":
        await query.edit_message_text(
            "💳 *Payment Required*\n\nYou need to pay ₹20 to unlock the quiz.\n\nClick the *Payment* button below to proceed.",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("💳 Make Payment", callback_data="payment")],
                [InlineKeyboardButton("🔙 Back to Menu", callback_data="back_to_menu")]
            ])
        )
    
    elif data == "set_upi":
        context.user_data["action"] = "set_upi"
        await query.edit_message_text(
            "💸 *Set UPI ID*\n\nPlease send your UPI ID.\n\nExample: username@okhdfcbank\n\n*Note: This is required to receive your prize money on Sunday!*",
            parse_mode="Markdown"
        )
        return UPI_INPUT
    
    elif data == "about":
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
        await query.edit_message_text(about_text, parse_mode="Markdown", reply_markup=get_main_keyboard(user_id))
    
    elif data == "back_to_menu":
        await query.edit_message_text("Main Menu:", reply_markup=get_main_keyboard(user_id))
    
    return ConversationHandler.END

# ========== REGISTRATION FLOW ==========
async def register_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Receive phone number"""
    phone = update.message.text.strip()
    context.user_data["reg_phone"] = phone
    
    await update.message.reply_text(
        "📝 *Registration*\n\nPlease send your *Password* (minimum 4 characters):",
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
        "payment_order_id": None,
        "answered_questions": [],
        "correct_answers": 0,
        "reward_pending": False,
        "registered_on": datetime.now().isoformat()
    }
    save_data("users.json", users)
    
    await update.message.reply_text(
        "✅ *Registration Successful!*\n\nYou can now:\n• Update your profile (Name, Place, Email)\n• Make payment of ₹20 to start quiz\n\nUse the buttons below:",
        parse_mode="Markdown",
        reply_markup=get_main_keyboard(user_id)
    )
    
    # Notify admin
    if ADMIN_ID:
        await context.bot.send_message(
            ADMIN_ID,
            f"🆕 New User Registered!\n\nUser ID: {user_id}\nPhone: {context.user_data['reg_phone']}"
        )
    
    return ConversationHandler.END

# ========== PROFILE FUNCTIONS ==========
async def show_profile(query, user_id):
    """Show user profile"""
    users = load_data("users.json")
    
    if str(user_id) not in users:
        await query.edit_message_text(
            "❌ You are not registered. Please click *Register* button first.",
            parse_mode="Markdown",
            reply_markup=get_main_keyboard(user_id)
        )
        return
    
    user = users[str(user_id)]
    
    profile_text = f"""
👤 *Your Profile*

📱 Phone: `{user.get('phone', 'Not set')}`
👨 Name: {user.get('name', 'Not set')}
📍 Place: {user.get('place', 'Not set')}
📧 Email: {user.get('email', 'Not set')}
💸 UPI ID: {user.get('upi_id', 'Not set')}

💰 Payment Status: {'✅ Paid' if user.get('payment_completed') else '❌ Not Paid'}
🎯 Correct Answers: {user.get('correct_answers', 0)}
🏆 Reward Pending: {'Yes' if user.get('reward_pending') else 'No'}

*To update your details, use the buttons below:* 👇
"""
    
    keyboard = [
        [InlineKeyboardButton("✏️ Update Name", callback_data="edit_name")],
        [InlineKeyboardButton("📍 Update Place", callback_data="edit_place")],
        [InlineKeyboardButton("📧 Update Email", callback_data="edit_email")],
        [InlineKeyboardButton("🔙 Back to Menu", callback_data="back_to_menu")]
    ]
    
    await query.edit_message_text(profile_text, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(keyboard))

async def edit_name_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start name edit"""
    query = update.callback_query
    await query.answer()
    context.user_data["action"] = "edit_name"
    await query.edit_message_text("✏️ Send your new *Name*:", parse_mode="Markdown")
    return EDIT_NAME

async def edit_name_save(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Save new name"""
    name = update.message.text.strip()
    user_id = update.effective_user.id
    
    users = load_data("users.json")
    if str(user_id) in users:
        users[str(user_id)]["name"] = name
        save_data("users.json", users)
        await update.message.reply_text("✅ Name updated successfully!", reply_markup=get_main_keyboard(user_id))
    else:
        await update.message.reply_text("❌ User not found. Please register first.", reply_markup=get_main_keyboard(user_id))
    
    return ConversationHandler.END

async def edit_place_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start place edit"""
    query = update.callback_query
    await query.answer()
    context.user_data["action"] = "edit_place"
    await query.edit_message_text("📍 Send your new *Place/City*:", parse_mode="Markdown")
    return EDIT_PLACE

async def edit_place_save(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Save new place"""
    place = update.message.text.strip()
    user_id = update.effective_user.id
    
    users = load_data("users.json")
    if str(user_id) in users:
        users[str(user_id)]["place"] = place
        save_data("users.json", users)
        await update.message.reply_text("✅ Place updated successfully!", reply_markup=get_main_keyboard(user_id))
    else:
        await update.message.reply_text("❌ User not found. Please register first.", reply_markup=get_main_keyboard(user_id))
    
    return ConversationHandler.END

async def edit_email_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start email edit"""
    query = update.callback_query
    await query.answer()
    context.user_data["action"] = "edit_email"
    await query.edit_message_text("📧 Send your new *Email*:", parse_mode="Markdown")
    return EDIT_EMAIL

async def edit_email_save(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Save new email"""
    email = update.message.text.strip()
    user_id = update.effective_user.id
    
    users = load_data("users.json")
    if str(user_id) in users:
        users[str(user_id)]["email"] = email
        save_data("users.json", users)
        await update.message.reply_text("✅ Email updated successfully!", reply_markup=get_main_keyboard(user_id))
    else:
        await update.message.reply_text("❌ User not found. Please register first.", reply_markup=get_main_keyboard(user_id))
    
    return ConversationHandler.END

# ========== UPI FUNCTIONS ==========
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
        
        # Notify admin
        if ADMIN_ID:
            await context.bot.send_message(
                ADMIN_ID,
                f"💰 New Winner!\n\nUser: {user_id}\nUPI: {upi_id}\n\nReady for Sunday payout!"
            )
    else:
        await update.message.reply_text("❌ Please register first using the Register button.", reply_markup=get_main_keyboard(user_id))
    
    return ConversationHandler.END

# ========== DEMO QUIZ ==========
async def start_demo_quiz(query, user_id, context):
    """Start demo quiz"""
    demo_data = load_data("demo_question.json")
    
    if not demo_data:
        demo_data = {
            "question": "What is the capital of France?",
            "options": ["London", "Berlin", "Paris", "Madrid"],
            "correct": "Paris"
        }
        save_data("demo_question.json", demo_data)
    
    q = demo_data
    
    # Store demo question in context
    context.user_data["demo_question"] = q
    context.user_data["demo_active"] = True
    
    options_text = "\n".join([f"{chr(65+i)}. {opt}" for i, opt in enumerate(q["options"])])
    
    keyboard = []
    for i, opt in enumerate(q["options"]):
        keyboard.append([InlineKeyboardButton(f"{chr(65+i)}. {opt}", callback_data=f"demo_answer_{opt}")])
    
    await query.edit_message_text(
        f"🎯 *DEMO QUIZ (FREE)*\n\n{q['question']}\n\n{options_text}\n\nSelect your answer:",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def demo_answer_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle demo quiz answer"""
    query = update.callback_query
    await query.answer()
    
    selected = query.data.replace("demo_answer_", "")
    demo_q = context.user_data.get("demo_question", {})
    
    if selected == demo_q.get("correct"):
        await query.edit_message_text(
            "✅ *Correct Answer!*\n\n📝 *Register a real account and join the Quiz for just ₹20 and win the prize of ₹1000!*\n\nUse the Register button below to get started.",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("📝 Register Now", callback_data="register")],
                [InlineKeyboardButton("🔙 Back to Menu", callback_data="back_to_menu")]
            ])
        )
    else:
        correct = demo_q.get("correct", "Unknown")
        await query.edit_message_text(
            f"❌ *Wrong Answer!*\n\nThe correct answer was: *{correct}*\n\n📝 *Register a real account and join the Quiz for just ₹20 and win the prize of ₹1000!*\n\nUse the Register button below to get started.",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("📝 Register Now", callback_data="register")],
                [InlineKeyboardButton("🔙 Back to Menu", callback_data="back_to_menu")]
            ])
        )
    
    context.user_data["demo_active"] = False

# ========== REAL QUIZ ==========
async def start_real_quiz(query, user_id, context):
    """Start real quiz (after payment)"""
    users = load_data("users.json")
    
    if str(user_id) not in users:
        await query.edit_message_text("❌ Please register first.", reply_markup=get_main_keyboard(user_id))
        return
    
    if not users[str(user_id)].get("payment_completed", False):
        await query.edit_message_text("❌ Please complete payment (₹20) first to start the quiz.", reply_markup=get_main_keyboard(user_id))
        return
    
    # Load questions
    questions = load_data("questions.json")
    if not questions:
        await query.edit_message_text("❌ No questions available. Admin will add questions soon.", reply_markup=get_main_keyboard(user_id))
        return
    
    # Get questions user hasn't answered
    answered = users[str(user_id)].get("answered_questions", [])
    available = [q for q in questions if q["id"] not in answered]
    
    if not available:
        await query.edit_message_text(
            "🎉 *Congratulations!* 🎉\n\nYou have answered all available questions!\n\nNew questions will be added soon. Stay tuned!",
            parse_mode="Markdown",
            reply_markup=get_main_keyboard(user_id)
        )
        return
    
    # Select random question
    import random
    question = random.choice(available)
    context.user_data["current_question"] = question
    
    options_text = "\n".join([f"{chr(65+i)}. {opt}" for i, opt in enumerate(question["options"])])
    
    keyboard = []
    for i, opt in enumerate(question["options"]):
        keyboard.append([InlineKeyboardButton(f"{chr(65+i)}. {opt}", callback_data=f"quiz_answer_{opt}_{question['id']}")])
    
    await query.edit_message_text(
        f"🎯 *QUIZ TIME!*\n\n*Question:* {question['text']}\n\n{options_text}\n\nSelect your answer:",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def quiz_answer_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle real quiz answer"""
    query = update.callback_query
    await query.answer()
    
    data_parts = query.data.split("_")
    selected = data_parts[2]
    question_id = data_parts[3]
    
    user_id = query.from_user.id
    question = context.user_data.get("current_question", {})
    
    if question.get("id") != question_id:
        await query.edit_message_text("❌ Quiz session expired. Please click Start Quiz again.", reply_markup=get_main_keyboard(user_id))
        return
    
    users = load_data("users.json")
    
    if selected == question.get("correct"):
        # Correct answer
        if str(user_id) in users:
            answered = users[str(user_id)].get("answered_questions", [])
            if question_id not in answered:
                answered.append(question_id)
                users[str(user_id)]["answered_questions"] = answered
                users[str(user_id)]["correct_answers"] = users[str(user_id)].get("correct_answers", 0) + 1
                save_data("users.json", users)
        
        await query.edit_message_text(
            "✅ *CORRECT ANSWER!* 🎉\n\n🏆 *Please click the UPI button below and fill your UPI ID.*\n\n💰 *Jannat Foundation will pay your prize on coming Sunday!*",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("💸 Set UPI ID", callback_data="set_upi")],
                [InlineKeyboardButton("🔙 Back to Menu", callback_data="back_to_menu")]
            ])
        )
        
        # Notify admin
        if ADMIN_ID:
            await context.bot.send_message(
                ADMIN_ID,
                f"✅ User {user_id} answered correctly!\nQuestion: {question.get('text')}\n\nAwaiting UPI submission."
            )
    
    else:
        # Wrong answer
        correct_answer = question.get("correct", "Unknown")
        await query.edit_message_text(
            f"❌ *WRONG ANSWER!*\n\nThe correct answer was: *{correct_answer}*\n\n💳 *Please pay ₹20 to try again with a new question.*\n\nClick the Payment button below:",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("💳 Pay ₹20", callback_data="payment")],
                [InlineKeyboardButton("🔙 Back to Menu", callback_data="back_to_menu")]
            ])
        )

# ========== PAYMENT FUNCTIONS ==========
async def create_payment(query, user_id):
    """Create Razorpay order"""
    users = load_data("users.json")
    
    if str(user_id) not in users:
        await query.edit_message_text("❌ Please register first.", reply_markup=get_main_keyboard(user_id))
        return
    
    try:
        # Create Razorpay order
        order_amount = 2000  # ₹20 in paise
        order_currency = "INR"
        
        order = razorpay_client.order.create({
            "amount": order_amount,
            "currency": order_currency,
            "payment_capture": 1,
            "notes": {
                "telegram_id": str(user_id)
            }
        })
        
        # Store order
        payments = load_data("payments.json")
        payments[str(order["id"])] = {
            "user_id": user_id,
            "amount": 20,
            "status": "pending",
            "created_at": datetime.now().isoformat()
        }
        save_data("payments.json", payments)
        
        # Send payment link
        payment_link = f"https://rzp.io/l/payment?order_id={order['id']}"
        
        await query.edit_message_text(
            f"💳 *Payment Required*\n\n💰 Amount: ₹20\n🆔 Order ID: `{order['id']}`\n\n*Click the link below to pay:*\n\n🔗 [Pay ₹20 via Razorpay]({payment_link})\n\n*After successful payment, click 'Start Quiz' to play!*",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("✅ I have completed payment", callback_data="check_payment")],
                [InlineKeyboardButton("🔙 Back to Menu", callback_data="back_to_menu")]
            ]),
            disable_web_page_preview=True
        )
        
    except Exception as e:
        logger.error(f"Payment error: {e}")
        await query.edit_message_text(
            "❌ Payment service temporarily unavailable. Please try again later.",
            reply_markup=get_main_keyboard(user_id)
        )

async def check_payment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Check payment status"""
    query = update.callback_query
    await query.answer()
    
    user_id = query.from_user.id
    payments = load_data("payments.json")
    users = load_data("users.json")
    
    # Find pending payment for this user
    user_payment = None
    for order_id, payment in payments.items():
        if payment["user_id"] == user_id and payment["status"] == "pending":
            user_payment = payment
            break
    
    if not user_payment:
        # Check if already verified
        if str(user_id) in users and users[str(user_id)].get("payment_completed"):
            await query.edit_message_text("✅ You already have an active quiz! Click 'Start Quiz' to play.", reply_markup=get_main_keyboard(user_id))
        else:
            await query.edit_message_text("❌ No pending payment found. Please make a new payment.", reply_markup=get_main_keyboard(user_id))
        return
    
    try:
        # Verify with Razorpay
        order_id = list(payments.keys())[list(payments.values()).index(user_payment)]
        order = razorpay_client.order.fetch(order_id)
        
        if order["status"] == "paid":
            # Update user
            users[str(user_id)]["payment_completed"] = True
            users[str(user_id)]["payment_order_id"] = order_id
            save_data("users.json", users)
            
            # Update payment status
            payments[order_id]["status"] = "completed"
            save_data("payments.json", payments)
            
            await query.edit_message_text(
                "✅ *Payment Successful!* 🎉\n\n🔓 *Start Quiz is now UNLOCKED!*\n\nClick the 'Start Quiz' button to play and win ₹1000!",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🎯 Start Quiz", callback_data="start_quiz")],
                    [InlineKeyboardButton("🔙 Back to Menu", callback_data="back_to_menu")]
                ])
            )
            
            # Notify admin
            if ADMIN_ID:
                await context.bot.send_message(
                    ADMIN_ID,
                    f"💳 Payment Completed!\nUser: {user_id}\nOrder: {order_id}"
                )
        else:
            await query.edit_message_text(
                f"⏳ Payment pending. Amount: ₹20\n\nPlease complete the payment using the link below:\n\nhttps://rzp.io/l/payment?order_id={order_id}\n\nAfter payment, click 'Check Payment' again.",
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔄 Check Again", callback_data="check_payment")],
                    [InlineKeyboardButton("🔙 Back to Menu", callback_data="back_to_menu")]
                ]),
                disable_web_page_preview=True
            )
    except Exception as e:
        logger.error(f"Payment check error: {e}")
        await query.edit_message_text("❌ Could not verify payment. Please try again in a few minutes.", reply_markup=get_main_keyboard(user_id))

# ========== ADMIN COMMANDS ==========
@admin_only
async def admin_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show admin statistics"""
    users = load_data("users.json")
    payments = load_data("payments.json")
    questions = load_data("questions.json")
    
    total_users = len(users)
    paid_users = sum(1 for u in users.values() if u.get("payment_completed"))
    correct_answers = sum(u.get("correct_answers", 0) for u in users.values())
    pending_rewards = sum(1 for u in users.values() if u.get("reward_pending") and u.get("upi_id"))
    total_payments = len([p for p in payments.values() if p.get("status") == "completed"])
    
    stats_text = f"""
📊 *Admin Statistics*

👥 Total Users: {total_users}
💰 Paid Users: {paid_users}
✅ Total Correct Answers: {correct_answers}
🏆 Pending Rewards: {pending_rewards}
💳 Total Payments: {total_payments}
📚 Questions in DB: {len(questions)}

*Commands:*
/add_question - Add new question
/update_demo - Update demo question
/pending_upi - View pending UPI payouts
/broadcast - Send message to all users
/reset_user - Reset user progress
"""
    await update.message.reply_text(stats_text, parse_mode="Markdown")

@admin_only
async def add_question(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Add new question via command"""
    args = context.args
    if len(args) < 6:
        await update.message.reply_text(
            "❌ *Usage:*\n/add_question \"Question\" \"Option1\" \"Option2\" \"Option3\" \"Option4\" \"Correct\"\n\n*Example:*\n/add_question \"What is 2+2?\" \"3\" \"4\" \"5\" \"6\" \"4\"",
            parse_mode="Markdown"
        )
        return
    
    question_text = args[0].strip('"')
    opt1 = args[1].strip('"')
    opt2 = args[2].strip('"')
    opt3 = args[3].strip('"')
    opt4 = args[4].strip('"')
    correct = args[5].strip('"')
    
    questions = load_data("questions.json")
    new_id = f"Q{len(questions) + 1}"
    
    questions.append({
        "id": new_id,
        "text": question_text,
        "options": [opt1, opt2, opt3, opt4],
        "correct": correct
    })
    
    save_data("questions.json", questions)
    await update.message.reply_text(f"✅ Question added successfully!\nID: {new_id}")

@admin_only
async def update_demo_question(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Update demo question"""
    args = context.args
    if len(args) < 6:
        await update.message.reply_text(
            "❌ *Usage:*\n/update_demo \"Question\" \"Option1\" \"Option2\" \"Option3\" \"Option4\" \"Correct\"\n\n*Example:*\n/update_demo \"What is the capital of India?\" \"Mumbai\" \"Delhi\" \"Kolkata\" \"Chennai\" \"Delhi\"",
            parse_mode="Markdown"
        )
        return
    
    demo_q = {
        "question": args[0].strip('"'),
        "options": [args[1].strip('"'), args[2].strip('"'), args[3].strip('"'), args[4].strip('"')],
        "correct": args[5].strip('"')
    }
    
    save_data("demo_question.json", demo_q)
    await update.message.reply_text("✅ Demo question updated successfully!")

@admin_only
async def pending_upi(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show users with pending UPI payouts"""
    users = load_data("users.json")
    pending = []
    
    for uid, user in users.items():
        if user.get("reward_pending") and user.get("upi_id"):
            pending.append(f"User: {uid}\n   Name: {user.get('name', 'N/A')}\n   UPI: {user.get('upi_id')}\n")
    
    if pending:
        await update.message.reply_text(f"💰 *Pending Payouts (Sunday)*\n\n{chr(10).join(pending)}", parse_mode="Markdown")
    else:
        await update.message.reply_text("No pending payouts at this time.")

@admin_only
async def broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Broadcast message to all users"""
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

@admin_only
async def reset_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Reset a user's quiz progress"""
    args = context.args
    if not args:
        await update.message.reply_text("❌ Usage: /reset_user USER_ID")
        return
    
    user_id = args[0]
    users = load_data("users.json")
    
    if user_id in users:
        users[user_id]["answered_questions"] = []
        users[user_id]["correct_answers"] = 0
        users[user_id]["payment_completed"] = False
        save_data("users.json", users)
        await update.message.reply_text(f"✅ User {user_id} has been reset.")
    else:
        await update.message.reply_text(f"❌ User {user_id} not found.")

# ========== MAIN FUNCTION ==========
def main():
    """Start the bot"""
    if not TOKEN:
        logger.error("No BOT_TOKEN provided!")
        return
    
    # Initialize data files
    for filename in DATA_FILES.values():
        if not os.path.exists(filename):
            if filename == "questions.json":
                save_data(filename, [])
            elif filename == "demo_question.json":
                default_demo = {
                    "question": "What is 2 + 2?",
                    "options": ["3", "4", "5", "6"],
                    "correct": "4"
                }
                save_data(filename, default_demo)
            else:
                save_data(filename, {})
    
    # Create application
    application = Application.builder().token(TOKEN).build()
    
    # Conversation handlers
    reg_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(button_handler, pattern="^register$")],
        states={
            PHONE_REG: [MessageHandler(filters.TEXT & ~filters.COMMAND, register_phone)],
            PASSWORD_REG: [MessageHandler(filters.TEXT & ~filters.COMMAND, register_password)],
        },
        fallbacks=[]
    )
    
    edit_name_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(edit_name_start, pattern="^edit_name$")],
        states={EDIT_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, edit_name_save)]},
        fallbacks=[]
    )
    
    edit_place_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(edit_place_start, pattern="^edit_place$")],
        states={EDIT_PLACE: [MessageHandler(filters.TEXT & ~filters.COMMAND, edit_place_save)]},
        fallbacks=[]
    )
    
    edit_email_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(edit_email_start, pattern="^edit_email$")],
        states={EDIT_EMAIL: [MessageHandler(filters.TEXT & ~filters.COMMAND, edit_email_save)]},
        fallbacks=[]
    )
    
    upi_conv = ConversationHandler(
        entry_points=[CallbackQueryHandler(button_handler, pattern="^set_upi$")],
        states={UPI_INPUT: [MessageHandler(filters.TEXT & ~filters.COMMAND, save_upi)]},
        fallbacks=[]
    )
    
    # Add handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(reg_conv)
    application.add_handler(edit_name_conv)
    application.add_handler(edit_place_conv)
    application.add_handler(edit_email_conv)
    application.add_handler(upi_conv)
    
    # Admin commands
    application.add_handler(CommandHandler("stats", admin_stats))
    application.add_handler(CommandHandler("add_question", add_question))
    application.add_handler(CommandHandler("update_demo", update_demo_question))
    application.add_handler(CommandHandler("pending_upi", pending_upi))
    application.add_handler(CommandHandler("broadcast", broadcast))
    application.add_handler(CommandHandler("reset_user", reset_user))
    
    # Callback handlers
    application.add_handler(CallbackQueryHandler(button_handler, pattern="^(register|profile|demo_quiz|start_quiz|payment|payment_info|set_upi|about|back_to_menu)$"))
    application.add_handler(CallbackQueryHandler(check_payment, pattern="^check_payment$"))
    application.add_handler(CallbackQueryHandler(demo_answer_handler, pattern="^demo_answer_"))
    application.add_handler(CallbackQueryHandler(quiz_answer_handler, pattern="^quiz_answer_"))
    application.add_handler(CallbackQueryHandler(edit_name_start, pattern="^edit_name$"))
    application.add_handler(CallbackQueryHandler(edit_place_start, pattern="^edit_place$"))
    application.add_handler(CallbackQueryHandler(edit_email_start, pattern="^edit_email$"))
    
    # Start bot
    print("🤖 Bot is running...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
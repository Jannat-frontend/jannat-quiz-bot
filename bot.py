import os
import json
import logging
import hashlib
import random
from datetime import datetime

from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, ConversationHandler, ContextTypes, filters

# ========== CONFIGURATION ==========
TOKEN = os.environ.get("BOT_TOKEN")
ADMIN_ID = int(os.environ.get("ADMIN_ID", "0"))

# States
PHONE_REG, PASSWORD_REG, UPI_INPUT = range(3)

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

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
        ["💳 Pay ₹1", "💸 Set UPI"],
    ]
    
    if is_registered and has_paid:
        keyboard.append(["🔓 Start Quiz"])
    else:
        keyboard.append(["🔒 Start Quiz"])
    
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

# ========== START ==========
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    print("✅ /start received")
    user = update.effective_user
    msg = f"""
🏆 *JANNAT FOUNDATION QUIZ* 🏆

Welcome {user.first_name}!

💰 *Win ₹1000!*

*Steps:*
1️⃣ Register
2️⃣ Pay ₹1
3️⃣ Answer 1 question
4️⃣ Submit UPI
5️⃣ Get ₹1000 on Sunday

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
        "answered_questions": [],
        "correct_answers": 0,
        "registered_on": datetime.now().isoformat()
    }
    save_data("users.json", users)
    
    await update.message.reply_text("✅ *Registration Successful!*", parse_mode="Markdown", reply_markup=get_keyboard(user_id))
    
    if ADMIN_ID:
        await context.bot.send_message(ADMIN_ID, f"🆕 New user: {user_id}\nPhone: {context.user_data['phone']}")
    
    return ConversationHandler.END

# ========== PROFILE ==========
async def show_profile(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    users = load_data("users.json")
    
    if str(user_id) not in users:
        await update.message.reply_text("❌ Register first.", reply_markup=get_keyboard(user_id))
        return
    
    u = users[str(user_id)]
    text = f"""
👤 *Your Profile*

📱 Phone: {u.get('phone', 'Not set')}
👨 Name: {u.get('name', 'Not set')}
📍 Place: {u.get('place', 'Not set')}
📧 Email: {u.get('email', 'Not set')}
💸 UPI: {u.get('upi_id', 'Not set')}

💰 Paid: {'✅ Yes' if u.get('payment_completed') else '❌ No'}
✅ Correct: {u.get('correct_answers', 0)}
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

# ========== PAYMENT ==========
async def payment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Send payment link"""
    print("💳 PAYMENT BUTTON CLICKED")
    user_id = update.effective_user.id
    users = load_data("users.json")
    
    if str(user_id) not in users:
        await update.message.reply_text("❌ Register first.", reply_markup=get_keyboard(user_id))
        return
    
    # Simple working payment link
    await update.message.reply_text(
        "💳 *PAY ₹1 NOW*\n\n"
        "🔗 https://razorpay.me/@jannatfoundation\n\n"
        "📝 *After payment, send your Transaction ID to @imtiazs37*\n\n"
        "Admin will verify and unlock your quiz.",
        parse_mode="Markdown",
        reply_markup=get_keyboard(user_id)
    )

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

# ========== START QUIZ ==========
async def start_quiz(update: Update, context: ContextTypes.DEFAULT_TYPE):
    print("🎯 START QUIZ CLICKED")
    user_id = update.effective_user.id
    users = load_data("users.json")
    
    if str(user_id) not in users:
        await update.message.reply_text("❌ Register first.", reply_markup=get_keyboard(user_id))
        return
    
    if not users[str(user_id)].get("payment_completed"):
        await update.message.reply_text(
            "❌ *Payment Required*\n\nClick '💳 Pay ₹1' to pay.\n\nAfter payment, admin will verify.",
            parse_mode="Markdown",
            reply_markup=get_keyboard(user_id)
        )
        return
    
    questions = load_data("questions.json")
    if not questions:
        questions = [
            {"id": "Q1", "text": "What is the capital of India?", "options": ["Mumbai", "Delhi", "Kolkata", "Chennai"], "correct": "Delhi"},
            {"id": "Q2", "text": "Who wrote the national anthem?", "options": ["Tagore", "Chattopadhyay", "Naidu", "Gandhi"], "correct": "Tagore"},
            {"id": "Q3", "text": "Which planet is called Red Planet?", "options": ["Mars", "Jupiter", "Venus", "Saturn"], "correct": "Mars"},
        ]
        save_data("questions.json", questions)
    
    answered = users[str(user_id)].get("answered_questions", [])
    available = [q for q in questions if q["id"] not in answered]
    
    if not available:
        await update.message.reply_text("🎉 You answered all questions! New ones coming soon.", reply_markup=get_keyboard(user_id))
        return
    
    q = random.choice(available)
    context.user_data["current_q"] = q
    context.user_data["awaiting_quiz"] = True
    
    text = f"🎯 *QUIZ*\n\n{q['text']}\n\n"
    for i, opt in enumerate(q["options"]):
        text += f"{chr(65+i)}. {opt}\n"
    text += "\n*Reply with A, B, C, or D*"
    
    await update.message.reply_text(text, parse_mode="Markdown")

async def handle_quiz(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.user_data.get("awaiting_quiz"):
        return
    
    user_id = update.effective_user.id
    answer = update.message.text.strip().upper()
    q = context.user_data.get("current_q", {})
    
    letters = {"A": 0, "B": 1, "C": 2, "D": 3}
    
    if answer in letters:
        selected = q["options"][letters[answer]]
        users = load_data("users.json")
        
        if selected == q.get("correct"):
            if str(user_id) in users:
                answered = users[str(user_id)].get("answered_questions", [])
                if q["id"] not in answered:
                    answered.append(q["id"])
                    users[str(user_id)]["answered_questions"] = answered
                    users[str(user_id)]["correct_answers"] = users[str(user_id)].get("correct_answers", 0) + 1
                    save_data("users.json", users)
            
            await update.message.reply_text(
                "✅ *CORRECT!* 🎉\n\nTap '💸 Set UPI' to claim ₹1000!",
                parse_mode="Markdown",
                reply_markup=get_keyboard(user_id)
            )
            
            if ADMIN_ID:
                await context.bot.send_message(ADMIN_ID, f"✅ User {user_id} answered correctly!")
        else:
            if str(user_id) in users:
                users[str(user_id)]["payment_completed"] = False
                save_data("users.json", users)
            
            await update.message.reply_text(
                f"❌ *WRONG!*\nCorrect: {q.get('correct')}\n\nPay ₹1 to try again.",
                parse_mode="Markdown",
                reply_markup=get_keyboard(user_id)
            )
    else:
        await update.message.reply_text("Reply with A, B, C, or D", reply_markup=get_keyboard(user_id))
    
    context.user_data["awaiting_quiz"] = False

# ========== ABOUT ==========
async def about(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = """
📖 *Jannat Foundation Quiz*

💰 Prize: ₹1000
🎯 1 Question
📅 Payout: Sunday

*Contact:* @imtiazs37
"""
    await update.message.reply_text(text, parse_mode="Markdown", reply_markup=get_keyboard(update.effective_user.id))

async def locked_quiz(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🔒 *Quiz Locked*\n\nPay ₹1 first using '💳 Pay ₹1' button.", parse_mode="Markdown", reply_markup=get_keyboard(update.effective_user.id))

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
        await context.bot.send_message(int(user_id), "✅ *Payment Verified!* 🔓 Tap '🔓 Start Quiz' to play!", parse_mode="Markdown")
    except:
        pass

async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("⛔ Not authorized.")
        return
    
    users = load_data("users.json")
    questions = load_data("questions.json")
    paid = sum(1 for u in users.values() if u.get("payment_completed"))
    
    await update.message.reply_text(f"📊 Stats\nUsers: {len(users)}\nPaid: {paid}\nQuestions: {len(questions)}")

async def add_q(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("⛔ Not authorized.")
        return
    
    args = context.args
    if len(args) < 6:
        await update.message.reply_text("Usage: /addq Question Opt1 Opt2 Opt3 Opt4 Correct")
        return
    
    questions = load_data("questions.json")
    q = {
        "id": f"Q{len(questions)+1}",
        "text": args[0],
        "options": [args[1], args[2], args[3], args[4]],
        "correct": args[5]
    }
    questions.append(q)
    save_data("questions.json", questions)
    await update.message.reply_text(f"✅ Added: {q['id']}")

# ========== MAIN ==========
def main():
    if not TOKEN:
        print("❌ No BOT_TOKEN!")
        return
    
    print(f"🤖 Bot starting...")
    print(f"👑 Admin ID: {ADMIN_ID}")
    
    # Init files
    for f in ["users.json", "questions.json"]:
        if not os.path.exists(f):
            save_data(f, {} if f != "questions.json" else [])
    
    # Create application
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
    
    # Direct button handlers (NO duplicates)
    app.add_handler(MessageHandler(filters.Regex("^👤 Profile$"), show_profile))
    app.add_handler(MessageHandler(filters.Regex("^🎯 Demo Quiz$"), demo_quiz))
    app.add_handler(MessageHandler(filters.Regex("^ℹ️ About$"), about))
    app.add_handler(MessageHandler(filters.Regex("^💳 Pay ₹1$"), payment))
    app.add_handler(MessageHandler(filters.Regex("^🔓 Start Quiz$"), start_quiz))
    app.add_handler(MessageHandler(filters.Regex("^🔒 Start Quiz$"), locked_quiz))
    
    # Answer handlers
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_demo))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_quiz))
    
    # Profile update handlers
    app.add_handler(MessageHandler(filters.Regex("^✏️ Name "), update_name))
    app.add_handler(MessageHandler(filters.Regex("^📍 Place "), update_place))
    app.add_handler(MessageHandler(filters.Regex("^📧 Email "), update_email))
    
    # Commands
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("verify", verify_user))
    app.add_handler(CommandHandler("stats", stats))
    app.add_handler(CommandHandler("addq", add_q))
    
    print("✅ Bot is running! Ready to receive messages.")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()

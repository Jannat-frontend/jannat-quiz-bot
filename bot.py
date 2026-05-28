
import os
import json
import logging
import hashlib
from datetime import datetime
from threading import Thread

from flask import Flask

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup
)

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

# ================= CONFIG =================
TOKEN = os.environ.get("BOT_TOKEN")
RAZORPAY_KEY_ID = os.environ.get("RAZORPAY_KEY_ID")
RAZORPAY_KEY_SECRET = os.environ.get("RAZORPAY_KEY_SECRET")

PHONE_REG, PASSWORD_REG, UPI_INPUT = range(3)

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)

logger = logging.getLogger(__name__)

# ================= KEEP ALIVE =================
web_app = Flask(__name__)

@web_app.route('/')
def home():
    return "Bot Running"

def run_web():
    port = int(os.environ.get("PORT", 10000))
    web_app.run(host="0.0.0.0", port=port)

def keep_alive():
    t = Thread(target=run_web)
    t.start()

# ================= RAZORPAY =================
razorpay_client = razorpay.Client(
    auth=(RAZORPAY_KEY_ID, RAZORPAY_KEY_SECRET)
)

# ================= FILES =================
USERS_FILE = "users.json"
PAYMENTS_FILE = "payments.json"
QUESTIONS_FILE = "questions.json"

# ================= HELPERS =================
def load_json(file, default):
    if os.path.exists(file):
        with open(file, "r", encoding="utf-8") as f:
            return json.load(f)
    return default

def save_json(file, data):
    with open(file, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)

def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()

def get_main_keyboard():
    keyboard = [
        [InlineKeyboardButton("📝 Register", callback_data="register")],
        [InlineKeyboardButton("💳 Pay ₹20", callback_data="payment")],
        [InlineKeyboardButton("🎯 Start Quiz", callback_data="quiz")],
        [InlineKeyboardButton("💸 Set UPI", callback_data="upi")],
        [InlineKeyboardButton("👤 Profile", callback_data="profile")]
    ]

    return InlineKeyboardMarkup(keyboard)
```
```python
# ================= START =================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):

    text = """
🏆 JANNAT FOUNDATION QUIZ

💰 Win ₹1000 Prize

1️⃣ Register
2️⃣ Pay ₹20
3️⃣ Start Quiz
4️⃣ Submit UPI
"""

    await update.message.reply_text(
        text,
        reply_markup=get_main_keyboard()
    )

# ================= REGISTER =================
async def register_start(update: Update, context: ContextTypes.DEFAULT_TYPE):

    query = update.callback_query
    await query.answer()

    await query.message.reply_text(
        "📱 Send Phone Number"
    )

    return PHONE_REG


async def register_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):

    context.user_data["phone"] = update.message.text

    await update.message.reply_text(
        "🔐 Send Password"
    )

    return PASSWORD_REG


async def register_password(update: Update, context: ContextTypes.DEFAULT_TYPE):

    password = update.message.text

    users = load_json(USERS_FILE, {})

    user_id = str(update.effective_user.id)

    users[user_id] = {
        "phone": context.user_data["phone"],
        "password": hash_password(password),
        "payment_completed": False,
        "upi_id": "",
        "correct_answers": 0
    }

    save_json(USERS_FILE, users)

    await update.message.reply_text(
        "✅ Registration Successful",
        reply_markup=get_main_keyboard()
    )

    return ConversationHandler.END

# ================= PROFILE =================
async def profile(update: Update, context: ContextTypes.DEFAULT_TYPE):

    query = update.callback_query
    await query.answer()

    users = load_json(USERS_FILE, {})

    uid = str(query.from_user.id)

    if uid not in users:
        await query.edit_message_text("❌ Register First")
        return

    user = users[uid]

    txt = f"""
👤 PROFILE

📱 Phone: {user['phone']}
💳 Paid: {user['payment_completed']}
💸 UPI: {user['upi_id']}
🏆 Correct Answers: {user['correct_answers']}
"""

    await query.edit_message_text(
        txt,
        reply_markup=get_main_keyboard()
    )
```
```python
# ================= PAYMENT =================
async def payment(update: Update, context: ContextTypes.DEFAULT_TYPE):

    query = update.callback_query
    await query.answer()

    try:

        order = razorpay_client.order.create({
            "amount": 2000,
            "currency": "INR",
            "payment_capture": 1
        })

        payments = load_json(PAYMENTS_FILE, {})

        payments[order["id"]] = {
            "user_id": query.from_user.id,
            "status": "pending"
        }

        save_json(PAYMENTS_FILE, payments)

        await query.edit_message_text(
            f"💳 PAY ₹20\n\nOrder ID:\n{order['id']}",
            reply_markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton(
                        "💳 Pay Now",
                        url="https://rzp.io/l/YOURPAYMENTLINK"
                    )
                ],
                [
                    InlineKeyboardButton(
                        "✅ Check Payment",
                        callback_data="check"
                    )
                ]
            ])
        )

    except Exception as e:
        logger.error(e)

        await query.edit_message_text(
            "❌ Payment Error"
        )

# ================= CHECK PAYMENT =================
async def check_payment(update: Update, context: ContextTypes.DEFAULT_TYPE):

    query = update.callback_query
    await query.answer()

    users = load_json(USERS_FILE, {})
    payments = load_json(PAYMENTS_FILE, {})

    uid = str(query.from_user.id)

    for order_id, payment in payments.items():

        if str(payment["user_id"]) == uid:

            users[uid]["payment_completed"] = True

            save_json(USERS_FILE, users)

            await query.edit_message_text(
                "✅ Payment Verified\n\n🎯 Quiz Unlocked",
                reply_markup=get_main_keyboard()
            )

            return

    await query.edit_message_text(
        "❌ No Payment Found"
    )

# ================= QUIZ =================
async def quiz(update: Update, context: ContextTypes.DEFAULT_TYPE):

    query = update.callback_query
    await query.answer()

    users = load_json(USERS_FILE, {})

    uid = str(query.from_user.id)

    if uid not in users:
        await query.edit_message_text("❌ Register First")
        return

    if not users[uid]["payment_completed"]:
        await query.edit_message_text("❌ Pay ₹20 First")
        return

    context.user_data["correct"] = "4"

    keyboard = [
        [InlineKeyboardButton("2", callback_data="a_2")],
        [InlineKeyboardButton("3", callback_data="a_3")],
        [InlineKeyboardButton("4", callback_data="a_4")],
        [InlineKeyboardButton("5", callback_data="a_5")]
    ]

    await query.edit_message_text(
        "🎯 What is 2 + 2 ?",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
```
```python
# ================= ANSWERS =================
async def answer(update: Update, context: ContextTypes.DEFAULT_TYPE):

    query = update.callback_query
    await query.answer()

    selected = query.data.replace("a_", "")

    correct = context.user_data.get("correct")

    users = load_json(USERS_FILE, {})

    uid = str(query.from_user.id)

    if selected == correct:

        users[uid]["correct_answers"] += 1

        save_json(USERS_FILE, users)

        await query.edit_message_text(
            "✅ Correct Answer\n\n💸 Now Submit UPI ID"
        )

    else:

        users[uid]["payment_completed"] = False

        save_json(USERS_FILE, users)

        await query.edit_message_text(
            "❌ Wrong Answer\n\nPay ₹20 Again",
            reply_markup=get_main_keyboard()
        )

# ================= UPI =================
async def upi(update: Update, context: ContextTypes.DEFAULT_TYPE):

    query = update.callback_query
    await query.answer()

    await query.message.reply_text(
        "💸 Send UPI ID"
    )

    return UPI_INPUT


async def save_upi(update: Update, context: ContextTypes.DEFAULT_TYPE):

    users = load_json(USERS_FILE, {})

    uid = str(update.effective_user.id)

    users[uid]["upi_id"] = update.message.text

    save_json(USERS_FILE, users)

    await update.message.reply_text(
        "✅ UPI Saved Successfully",
        reply_markup=get_main_keyboard()
    )

    return ConversationHandler.END

# ================= MAIN =================
def main():

    app = Application.builder().token(TOKEN).build()

    register_conv = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(register_start, pattern="^register$")
        ],
        states={
            PHONE_REG: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, register_phone)
            ],
            PASSWORD_REG: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, register_password)
            ]
        },
        fallbacks=[]
    )

    upi_conv = ConversationHandler(
        entry_points=[
            CallbackQueryHandler(upi, pattern="^upi$")
        ],
        states={
            UPI_INPUT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, save_upi)
            ]
        },
        fallbacks=[]
    )

    app.add_handler(CommandHandler("start", start))

    app.add_handler(register_conv)
    app.add_handler(upi_conv)

    app.add_handler(CallbackQueryHandler(profile, pattern="^profile$"))
    app.add_handler(CallbackQueryHandler(payment, pattern="^payment$"))
    app.add_handler(CallbackQueryHandler(check_payment, pattern="^check$"))
    app.add_handler(CallbackQueryHandler(quiz, pattern="^quiz$"))
    app.add_handler(CallbackQueryHandler(answer, pattern="^a_"))

    print("🤖 Bot Running")

    app.run_polling()

if __name__ == "__main__":

    keep_alive()

    main()
```

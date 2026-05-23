# Jannat Foundation Quiz Bot

## Setup Instructions

### 1. Create Bot on Telegram
- Message @BotFather on Telegram
- Send `/newbot` and follow instructions
- Save the bot token

### 2. Deploy on Render.com (Free, 24/7)

1. Create a GitHub repository and upload these files
2. Go to [render.com](https://render.com) and sign up
3. Click "New +" → "Background Worker"
4. Connect your GitHub repository
5. Add environment variables:
   - `BOT_TOKEN` = your bot token
   - `RAZORPAY_KEY_ID` = rzp_test_OUGnz1rs9k9vFW
   - `RAZORPAY_KEY_SECRET` = your test secret
   - `ADMIN_ID` = your numeric Telegram ID
6. Click "Create Web Service"

### 3. Admin Commands
- `/stats` - View statistics
- `/add_question` - Add new quiz question
- `/update_demo` - Update demo question
- `/pending_upi` - View UPI payouts
- `/broadcast` - Message all users
- `/reset_user` - Reset user progress

## Bot Features
- Registration with phone & password
- Editable profile (name, place, email)
- Demo quiz (admin editable)
- ₹20 payment via Razorpay
- 1 question quiz, no repeats
- UPI collection for winners
- Sunday payout tracking
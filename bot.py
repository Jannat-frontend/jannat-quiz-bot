# ========== UPDATED QUIZ WITH 7-SECOND TIMER ==========

# Add this at the top with other imports
import asyncio

# Store timer tasks per user
user_timers = {}

def send_question(chat_id, index):
    """Send a quiz question with 7-second timer"""
    if index >= len(QUIZ_QUESTIONS):
        users = load_users()
        score = users[str(chat_id)].get("current_quiz_score", 0)
        users[str(chat_id)]["quiz_active"] = False
        save_users(users)
        set_user_state(chat_id, None)
        
        if score == 3:
            send_telegram_message(
                chat_id,
                f"🎉 *PERFECT SCORE!* 🎉\n\nYour score: {score}/3\n\n🏆 *You won ₹1000!*\n\nTap '💸 Set UPI' to claim your prize!",
                parse_mode="Markdown",
                reply_markup=get_keyboard(chat_id)
            )
        else:
            send_telegram_message(
                chat_id,
                f"📊 *Quiz Completed!*\n\nYour score: {score}/3\n\nThank you for participating!",
                parse_mode="Markdown",
                reply_markup=get_keyboard(chat_id)
            )
        return
    
    q = QUIZ_QUESTIONS[index]
    set_user_data(chat_id, "current_q", q)
    set_user_data(chat_id, "current_q_index", index)
    
    # Show timer warning
    text = f"🎯 *Question {index+1}/3* ⏱️ *7 seconds remaining*\n\n{q['text']}\n\nA. {q['options'][0]}\nB. {q['options'][1]}\nC. {q['options'][2]}\nD. {q['options'][3]}\n\n*Reply with A, B, C, or D (7 seconds!)*"
    send_telegram_message(chat_id, text, parse_mode="Markdown")
    
    # Cancel existing timer for this user
    if chat_id in user_timers:
        user_timers[chat_id].cancel()
    
    # Create new 7-second timer
    async def time_out():
        await asyncio.sleep(7)
        # Check if user is still on this question
        current_q = get_user_data(chat_id, "current_q")
        if current_q and current_q.get("id") == q.get("id"):
            send_telegram_message(chat_id, "⏰ *Time's up!* Moving to next question...", parse_mode="Markdown")
            send_question(chat_id, index + 1)
            if chat_id in user_timers:
                del user_timers[chat_id]
    
    timer_task = asyncio.create_task(time_out())
    user_timers[chat_id] = timer_task

def handle_quiz_answer(chat_id, answer):
    """Handle quiz answer - cancel timer if answer given"""
    users = load_users()
    
    if not users.get(str(chat_id), {}).get("quiz_active"):
        return
    
    # Cancel timer if user answered
    if chat_id in user_timers:
        user_timers[chat_id].cancel()
        del user_timers[chat_id]
    
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

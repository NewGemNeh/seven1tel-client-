import json
import re
import time
import telebot
from telebot import types
from config import *
from database import get_all_users, assign_number_to_user, release_user_number, get_db, init_db

# --- INGANTA GUDU (MULTITHREADING) ---
bot = telebot.TeleBot(BOT_TOKEN, threaded=True, num_threads=20)

user_states = {}
last_number_time = {}

# ======================
# 🚀 NOTIFICATION SYSTEM
# ======================
def send_stock_alert(country_name, flag, service, count):
    msg = f"""<blockquote>🚀 <b>NEW STOCK ADDED!</b>\n\n🌍 <b>Country:</b> {flag} {country_name}\n🛠 <b>Service:</b> {service}\n🔢 <b>Quantity:</b> {count} Numbers\n\n<i>Available now! Tap \"Get Number\" to buy.</i></blockquote>"""
    users = get_all_users()
    for u in users:
        try: 
            bot.send_message(u['user_id'], msg, parse_mode="HTML")
        except: 
            pass
    try: 
        bot.send_message(OTP_LOG_GROUP_ID, msg, parse_mode="HTML")
    except: 
        pass

def manual_broadcast(text):
    msg = f"<blockquote>📢 <b>ADMIN BROADCAST</b>\n\n{text}</blockquote>"
    users = get_all_users()
    for u in users:
        try: 
            bot.send_message(u['user_id'], msg, parse_mode="HTML")
        except: 
            pass

# ======================
# 🎮 USER UI
# ======================
@bot.message_handler(commands=['start'])
def start(message):
    conn = get_db()
    c = conn.cursor()
    c.execute("""
        INSERT INTO users (user_id)
        VALUES (%s)
        ON CONFLICT (user_id) DO NOTHING
    """, (message.from_user.id,))
    conn.commit()
    conn.close()
    select_service(message)

def select_service(message):
    m = types.InlineKeyboardMarkup(row_width=1)
    m.add( 
        types.InlineKeyboardButton("📱 Telegram", callback_data="srv_Telegram", style="primary"), 
        types.InlineKeyboardButton("💬 WhatsApp", callback_data="srv_WhatsApp", style="success"), 
        types.InlineKeyboardButton("👤 Facebook", callback_data="srv_Facebook", style="primary"), 
        types.InlineKeyboardButton("📦 Others", callback_data="srv_Others", style="danger"), 
        types.InlineKeyboardButton("🔄 Refresh", callback_data="refresh_services", style="primary") 
    )
    bot.send_message(message.chat.id, "🛠 <b>Select Service:</b>", reply_markup=m, parse_mode="HTML")

# ==========================================
# 🌍 SERVICE SELECTION
# ==========================================
@bot.callback_query_handler(func=lambda call: call.data.startswith("srv_"))
def srv_sel(call):
    srv = call.data.split("_")[1]
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT DISTINCT country_code FROM combos WHERE service=%s", (srv,))
    rows = c.fetchall()
    conn.close()

    # FIX: RealDictCursor returns dicts, not tuples - use key access
    codes = [r['country_code'] for r in rows]

    if not codes:
        bot.answer_callback_query(call.id, f"❌ No numbers available for {srv}!", show_alert=True)
        return

    bot.answer_callback_query(call.id)
    m = types.InlineKeyboardMarkup(row_width=1)
    for c in codes:
        name, flag = COUNTRY_DATA.get(c, (c, "🌍"))
        m.add(types.InlineKeyboardButton(f"{flag} {name}", callback_data=f"cnt_{c}_{srv}", style="primary"))
    m.add(types.InlineKeyboardButton("🔙 Back", callback_data="back_srv", style="danger"))
    bot.edit_message_text(f"🌍 <b>Select Country for {srv}:</b>", call.message.chat.id, call.message.message_id, reply_markup=m, parse_mode="HTML")

# ==========================================
# 💎 CLEAN NUMBER DISTRIBUTION (FINAL VERSION)
# ==========================================
@bot.callback_query_handler(func=lambda call: call.data.startswith("cnt_"))
def cnt_sel(call):
    bot.answer_callback_query(call.id)
    _, code, srv = call.data.split("_")
    user_id = call.from_user.id

    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT numbers FROM combos WHERE country_code=%s AND service=%s", (code, srv))
    row = c.fetchone()

    if not row or not json.loads(row['numbers']):
        conn.close()
        bot.answer_callback_query(call.id, "❌ Out of Stock!", show_alert=True)
        return

    all_nums = json.loads(row['numbers'])
    selected_nums = all_nums[:5]
    remaining = all_nums[5:]

    c.execute("UPDATE combos SET numbers=%s WHERE country_code=%s AND service=%s", (json.dumps(remaining), code, srv))
    conn.commit()
    conn.close()

    # === ASSIGN NUMBERS TO USER ===
    if selected_nums:
        release_user_number(user_id)
        for num in selected_nums:
            clean_num = num.lstrip('+')
            assign_number_to_user(
                user_id=user_id,
                number=clean_num,
                country_code=code,
                service=srv
            )

    name, flag = COUNTRY_DATA.get(code, (code, "🌍"))
    last_number_time[user_id] = time.time()

    # === INLINE KEYBOARD ===
    m = types.InlineKeyboardMarkup(row_width=1)
    for num in selected_nums:
        m.add(types.InlineKeyboardButton(
            text=f"{flag} +{num}", 
            copy_text=types.CopyTextButton(text=f"+{num}"),
            style="primary"
        ))

    m.add(
        types.InlineKeyboardButton("🔄 Change Number", callback_data=f"change_{code}_{srv}", style="danger"),
        types.InlineKeyboardButton("🌐 Change Country", callback_data=f"chcountry_{srv}", style="primary"),
        types.InlineKeyboardButton("🔑 Get OTP ↗", url=OTP_GROUP_LINK, style="success")
    )

    # === CLEAN MESSAGE (Exactly as requested) ===
    bot.edit_message_text(
        f"{flag} <b>{name} Numbers Assigned!</b>\n\n"
        f"⏳ <i>Waiting for OTP...</i>\n"
        f"<i>All OTPs will be forwarded to you automatically.</i>",
        call.message.chat.id,
        call.message.message_id,
        reply_markup=m,
        parse_mode="HTML"
    )

# ==========================================
# 🔄 OTHER HANDLERS
# ==========================================
@bot.callback_query_handler(func=lambda call: call.data == "refresh_services")
def refresh_services(call):
    bot.answer_callback_query(call.id, "✅ Refreshed successfully!", show_alert=True)

@bot.callback_query_handler(func=lambda call: call.data.startswith("chcountry_"))
def change_country(call):
    srv = call.data.split("_")[1]
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT DISTINCT country_code FROM combos WHERE service=%s", (srv,))
    rows = c.fetchall()
    conn.close()

    # FIX: RealDictCursor returns dicts, not tuples - use key access
    codes = [r['country_code'] for r in rows]

    if not codes:
        bot.answer_callback_query(call.id, f"❌ No countries available for {srv}!", show_alert=True)
        return

    bot.answer_callback_query(call.id)
    m = types.InlineKeyboardMarkup(row_width=1)
    for c in codes:
        name, flag = COUNTRY_DATA.get(c, (c, "🌍"))
        m.add(types.InlineKeyboardButton(f"{flag} {name}", callback_data=f"cnt_{c}_{srv}", style="primary"))
    m.add(types.InlineKeyboardButton("🔙 Back", callback_data="back_srv", style="danger"))
    bot.edit_message_text(f"🌍 <b>Select Country for {srv}:</b>", call.message.chat.id, call.message.message_id, reply_markup=m, parse_mode="HTML")

@bot.callback_query_handler(func=lambda call: call.data.startswith("change_"))
def change_number(call):
    user_id = call.from_user.id
    if user_id in last_number_time:
        elapsed = time.time() - last_number_time[user_id]
        if elapsed < 10:
            bot.answer_callback_query(call.id, f"⏳ Wait {int(10-elapsed)}s!", show_alert=True)
            return
    release_user_number(user_id)
    cnt_sel(call)

# ======================
# 🔐 ADMIN HANDLERS
# ======================
@bot.message_handler(commands=['admin'])
def admin_command(message):
    if message.chat.id in ADMIN_IDS:
        m = types.InlineKeyboardMarkup(row_width=1)
        m.add(types.InlineKeyboardButton("📥 Add Stock", callback_data="adm_add", style="success"),
              types.InlineKeyboardButton("🗑 Delete Stock", callback_data="adm_del", style="danger"),
              types.InlineKeyboardButton("📢 Broadcast", callback_data="adm_bc", style="primary"))
        bot.send_message(message.chat.id, "🔐 <b>Admin Panel</b>", reply_markup=m, parse_mode="HTML")

@bot.callback_query_handler(func=lambda call: call.data == "adm_bc")
def bc_req(call):
    user_states[call.from_user.id] = "bc_msg"
    bot.send_message(call.message.chat.id, "💬 <b>Send message to broadcast:</b>", parse_mode="HTML")

@bot.message_handler(func=lambda m: user_states.get(m.from_user.id) == "bc_msg")
def bc_process(message):
    manual_broadcast(message.text)
    bot.reply_to(message, "✅ Broadcast Sent!")
    del user_states[message.from_user.id]

@bot.callback_query_handler(func=lambda call: call.data == "adm_del")
def delete_stock_menu(call):
    m = types.InlineKeyboardMarkup(row_width=2)
    for s in ["Telegram", "WhatsApp", "Facebook", "Others"]:
        m.add(types.InlineKeyboardButton(f"Clear {s}", callback_data=f"purge_{s}", style="danger"))
    bot.edit_message_text("🗑️ <b>Select database to clear:</b>", call.message.chat.id, call.message.message_id, reply_markup=m, parse_mode="HTML")

@bot.callback_query_handler(func=lambda call: call.data.startswith("purge_"))
def process_purge(call):
    srv = call.data.split("_")[1]
    conn = get_db()
    c = conn.cursor()
    c.execute("DELETE FROM combos WHERE service=%s", (srv,))
    conn.commit()
    conn.close()
    bot.answer_callback_query(call.id, f"✅ Cleared {srv} stock.", show_alert=True)

@bot.callback_query_handler(func=lambda call: call.data == "adm_add")
def add_stock_srv(call):
    m = types.InlineKeyboardMarkup(row_width=2)
    for s in ["Telegram", "WhatsApp", "Facebook", "Others"]:
        m.add(types.InlineKeyboardButton(s, callback_data=f"upload_{s}", style="success"))
    bot.edit_message_text("🛠 <b>Select service:</b>", call.message.chat.id, call.message.message_id, reply_markup=m, parse_mode="HTML")

@bot.callback_query_handler(func=lambda call: call.data.startswith("upload_"))
def start_upload(call):
    srv = call.data.split("_")[1]
    user_states[call.from_user.id] = f"file_{srv}"
    bot.send_message(call.message.chat.id, f"📥 <b>Upload .txt file for {srv}:</b>", parse_mode="HTML")

@bot.message_handler(content_types=['document'])
def handle_file(message):
    state = user_states.get(message.from_user.id, "")
    if "file_" in state:
        srv = state.split("_")[1]
        file_info = bot.get_file(message.document.file_id)
        downloaded = bot.download_file(file_info.file_path).decode('utf-8')
        nums = [re.sub(r'[^\d]', '', n) for n in downloaded.splitlines() if len(n) > 8]
        code = "1"
        for c in COUNTRY_DATA.keys():
            if any(n.startswith(c) for n in nums[:5]):
                code = c
                break
        conn = get_db()
        c = conn.cursor()
        c.execute("INSERT INTO combos (country_code, service, numbers) VALUES (%s, %s, %s)", (code, srv, json.dumps(nums)))
        conn.commit()
        conn.close()
        bot.reply_to(message, f"✅ Added {len(nums)} numbers.")
        name, flag = COUNTRY_DATA.get(code, (code, "🌍"))
        send_stock_alert(name, flag, srv, len(nums))
        del user_states[message.from_user.id]

# ======================
# 🔄 NAVIGATION
# ======================
@bot.callback_query_handler(func=lambda call: call.data == "back_srv")
def back_srv(call):
    bot.answer_callback_query(call.id)
    m = types.InlineKeyboardMarkup(row_width=1)
    m.add( 
        types.InlineKeyboardButton("📱 Telegram", callback_data="srv_Telegram", style="primary"), 
        types.InlineKeyboardButton("💬 WhatsApp", callback_data="srv_WhatsApp", style="success"), 
        types.InlineKeyboardButton("👤 Facebook", callback_data="srv_Facebook", style="primary"), 
        types.InlineKeyboardButton("📦 Others", callback_data="srv_Others", style="danger"), 
        types.InlineKeyboardButton("🔄 Refresh", callback_data="refresh_services", style="primary") 
    )
    bot.edit_message_text("🛠 <b>Select Service:</b>", call.message.chat.id, call.message.message_id, reply_markup=m, parse_mode="HTML")

# ======================
# 🚀 RUN BOT
# ======================
def run_bot():
    # Initialize database before starting bot
    init_db()
    print("[SERVER] Bot is live! PostgreSQL + Full OTP assignment active.")
    bot.infinity_polling(timeout=60, long_polling_timeout=5)

if __name__ == "__main__":
    run_bot()

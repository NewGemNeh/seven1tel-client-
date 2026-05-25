import re
import json
import time
import requests
from datetime import datetime
from bs4 import BeautifulSoup
from config import *
from database import get_user_by_number, save_otp_log, is_otp_processed

session = requests.Session()
session.headers.update({
    "User-Agent": "Mozilla/5.0 (Linux; Android 15; 25078RA3EA) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.6778.260 Mobile Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "en-GB,en-US;q=0.9,en;q=0.8",
})

last_seen = set()
bot_instance = None  # Will be set by main.py

def set_bot(bot):
    global bot_instance
    bot_instance = bot

def solve_captcha(html):
    soup = BeautifulSoup(html, 'html.parser')
    text = soup.get_text()
    
    match = re.search(r'(\d+)\s*([+\-*/])\s*(\d+)', text)
    if match:
        a, op, b = int(match.group(1)), match.group(2), int(match.group(3))
        if op == '+': return str(a + b)
        elif op == '-': return str(a - b)
        elif op == '*': return str(a * b)
        elif op == '/': return str(a // b) if b != 0 else "1"
    
    number_match = re.search(r'(\d{1,3})\s*[+\-*/]\s*(\d{1,3})', text)
    if number_match:
        a, b = int(number_match.group(1)), int(number_match.group(2))
        op_match = re.search(r'[+\-*/]', text[number_match.start():number_match.end()+5])
        if op_match:
            op = op_match.group()
            if op == '+': return str(a + b)
            elif op == '-': return str(a - b)
            elif op == '*': return str(a * b)
            elif op == '/': return str(a // b) if b != 0 else "1"
    
    return "18"

def login():
    try:
        r1 = session.get(f"{PANEL_BASE_URL}/ints/login", timeout=15)
        captcha = solve_captcha(r1.text)
        
        r2 = session.post(f"{PANEL_BASE_URL}/ints/signin", data={
            "username": PANEL_USERNAME,
            "password": PANEL_PASSWORD,
            "capt": captcha
        }, allow_redirects=True, timeout=15)
        
        if "login" in r2.text.lower() and "logout" not in r2.text.lower():
            print(f"[MONITOR] ❌ Login failed (captcha answer was: {captcha})")
            return False
        
        # Client Panel Paths
        session.get(f"{PANEL_BASE_URL}/ints/client/SMSDashboard", timeout=10)
        session.get(f"{PANEL_BASE_URL}/ints/client/SMSCDRStats", timeout=10)
        
        print("[MONITOR] ✅ Login successful")
        return True
        
    except Exception as e:
        print(f"[MONITOR] ❌ Login error: {e}")
        return False

def fetch_sms():
    try:
        now = datetime.now()
        params = {
            "fdate1": now.strftime("%Y-%m-%d 00:00:00"),
            "fdate2": now.strftime("%Y-%m-%d %H:%M:%S"),
            "fg": "0",
            "sEcho": "1",
            "iColumns": "7",
            "iDisplayStart": "0",
            "iDisplayLength": "50",
            "iSortCol_0": "0",
            "sSortDir_0": "desc",
            "_": str(int(time.time() * 1000))
        }
        
        headers = session.headers.copy()
        headers.update({
            "X-Requested-With": "XMLHttpRequest",
            "Referer": f"{PANEL_BASE_URL}/ints/client/SMSCDRStats"
        })
        
        r = session.get(
            f"{PANEL_BASE_URL}/ints/client/res/data_smscdr.php",
            params=params,
            headers=headers,
            timeout=15
        )
        
        data = json.loads(r.text)
        return data.get('aaData', [])
        
    except Exception as e:
        print(f"[MONITOR] ❌ Fetch error: {e}")
        return []

def extract_otp(msg):
    if not msg:
        return None
    msg = str(msg).lower()
    
    match = re.search(r'(?:code|otp|pin|codigo|código|contraseña|password|verify|verification|كود|رمز)\s*[:.]?\s*(\d{4,8})', msg, re.IGNORECASE)
    if match:
        return match.group(1)
    
    match = re.search(r'\b(\d{3}[-]\d{3})\b', msg)
    if match:
        return match.group(1).replace('-', '')
    
    if any(kw in msg for kw in ['code', 'otp', 'pin', 'verify', 'login', 'confirm']):
        match = re.search(r'\b(\d{4,6})\b', msg)
        if match:
            return match.group(1)
    
    return None

def detect_service(sender, msg):
    sender_lower = str(sender).lower() if sender else ""
    msg_lower = str(msg).lower() if msg else ""
    combined = sender_lower + " " + msg_lower
    
    for service, keywords in SERVICE_KEYWORDS.items():
        for kw in keywords:
            if kw in combined:
                return service.capitalize()
    
    return "Unknown"

def get_country_info(number):
    number = str(number).strip().lstrip('+')
    sorted_codes = sorted(COUNTRY_DATA.keys(), key=lambda x: len(x), reverse=True)
    for code in sorted_codes:
        if number.startswith(code):
            return COUNTRY_DATA[code]
    return ("Unknown", "🌐")

def monitor_loop():
    global last_seen
    
    print("[MONITOR] Starting SMS monitor...")
    
    if not login():
        print("[MONITOR] Initial login failed. Retrying in 30s...")
        time.sleep(30)
        if not login():
            print("[MONITOR] Failed to login. Exiting monitor.")
            return
    
    print("[MONITOR] Seeding existing messages...")
    rows = fetch_sms()
    for row in rows:
        if row and len(row) >= 6:
            uid = f"{row[0]}|{row[2]}|{row[5]}"
            last_seen.add(uid)
    print(f"[MONITOR] Seeded {len(last_seen)} existing messages")
    
    check = 0
    last_login = time.time()
    
    while True:
        try:
            check += 1
            
            if time.time() - last_login > SESSION_REFRESH:
                print("[MONITOR] Refreshing session...")
                login()
                last_login = time.time()
            
            rows = fetch_sms()
            
            for row in rows:
                if not row or len(row) < 6:
                    continue
                
                if str(row[5]) == "0" and str(row[2]) == "0":
                    continue
                
                uid = f"{row[0]}|{row[2]}|{row[5]}"
                if uid in last_seen:
                    continue
                
                last_seen.add(uid)
                
                if len(last_seen) > MAX_LAST_SEEN:
                    last_seen = set(list(last_seen)[-MAX_LAST_SEEN//2:])
                
                ts = row[0] or "?"
                sender = row[1] or "?"
                number = str(row[2]).strip() if row[2] else ""
                msg = str(row[5]) if row[5] else ""
                
                otp = extract_otp(msg)
                
                if otp and number:
                    if is_otp_processed(number, otp):
                        continue
                    
                    user = get_user_by_number(number)
                    
                    if user:
                        country_name, flag = get_country_info(number)
                        service = user.get('service', detect_service(sender, msg))
                        
                        # NEW OTP STYLE
                        message = (
                            f"🗺️ Country: {flag} {country_name}\n"
                            f"📱 Platform: {service}\n"
                            f"☎️ Number: +{number}\n"
                            f"🛡️ OTP Code: {otp} ✅\n"
                        )
                        
                        if bot_instance:
                            try:
                                bot_instance.send_message(user['user_id'], message, parse_mode="HTML")
                                print(f"[MONITOR] ✅ OTP sent to user {user['user_id']}: {otp} for {number}")
                            except Exception as e:
                                print(f"[MONITOR] ❌ Failed to send to user: {e}")
                        
                        if bot_instance and OTP_LOG_GROUP_ID:
                            try:
                                bot_instance.send_message(OTP_LOG_GROUP_ID, message, parse_mode="HTML")
                            except Exception as e:
                                print(f"[MONITOR] ❌ Failed to send to log group: {e}")
                        
                        save_otp_log(user['user_id'], number, service, otp, sender, msg)
            
            if check % 10 == 0:
                print(f"[MONITOR] ✓ Running... (checked {check} times, {len(last_seen)} cached)")
            
            time.sleep(POLL_INTERVAL)
            
        except Exception as e:
            print(f"[MONITOR] ❌ Loop error: {e}")
            time.sleep(5)

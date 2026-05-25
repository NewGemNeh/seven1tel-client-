import threading
import sys
from database import init_db
from monitor import monitor_loop, set_bot
from bot import bot, run_bot

def main():
    print("=" * 50)
    print("🔐 OTP AUTO-DELIVERY BOT")
    print("=" * 50)
    
    # Initialize database
    init_db()
    print("[MAIN] ✅ Database initialized")
    
    # Set bot instance in monitor
    set_bot(bot)
    print("[MAIN] ✅ Bot linked to monitor")
    
    # Start threads
    print("[MAIN] 🚀 Starting threads...")
    
    t_bot = threading.Thread(target=run_bot, daemon=True)
    t_monitor = threading.Thread(target=monitor_loop, daemon=True)
    
    t_bot.start()
    t_monitor.start()
    
    print("[MAIN] ✅ Both threads running")
    print("[MAIN] 📱 Bot ready - open Telegram and send /start")
    print("[MAIN] 📡 Monitor polling SMS panel every 10s")
    print("-" * 50)
    
    # Keep main thread alive
    try:
        t_bot.join()
        t_monitor.join()
    except KeyboardInterrupt:
        print("\n[MAIN] ⏹️ Shutting down...")
        sys.exit(0)

if __name__ == "__main__":
    main()

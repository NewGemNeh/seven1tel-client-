import psycopg2
from psycopg2.extras import RealDictCursor
from datetime import datetime
import json
from config import DATABASE_URL

def get_db():
    conn = psycopg2.connect(
        DATABASE_URL,
        cursor_factory=RealDictCursor
    )
    return conn

def init_db():
    conn = get_db()
    c = conn.cursor()

    # Users table
    c.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id BIGINT PRIMARY KEY,
            username TEXT,
            first_name TEXT,
            status TEXT DEFAULT 'none',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # User numbers table
    c.execute("""
        CREATE TABLE IF NOT EXISTS user_numbers (
            id SERIAL PRIMARY KEY,
            user_id BIGINT REFERENCES users(user_id) ON DELETE CASCADE,
            number TEXT NOT NULL UNIQUE,
            country_code TEXT NOT NULL,
            service TEXT NOT NULL,
            assigned_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            status TEXT DEFAULT 'active',
            is_primary BOOLEAN DEFAULT false
        )
    """)

    # Combos table
    c.execute("""
        CREATE TABLE IF NOT EXISTS combos (
            id SERIAL PRIMARY KEY,
            country_code TEXT NOT NULL,
            service TEXT NOT NULL,
            numbers TEXT
        )
    """)

    # OTP logs table
    c.execute("""
        CREATE TABLE IF NOT EXISTS otp_logs (
            id SERIAL PRIMARY KEY,
            user_id BIGINT,
            number TEXT NOT NULL,
            service TEXT NOT NULL,
            otp_code TEXT NOT NULL,
            sender TEXT,
            message_body TEXT,
            received_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # Processed OTPs table
    c.execute("""
        CREATE TABLE IF NOT EXISTS processed_otps (
            id SERIAL PRIMARY KEY,
            number TEXT NOT NULL,
            otp_code TEXT NOT NULL,
            received_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(number, otp_code)
        )
    """)

    # Create indexes for faster lookups
    c.execute("""
        CREATE INDEX IF NOT EXISTS idx_user_numbers_user_id 
        ON user_numbers(user_id)
    """)

    c.execute("""
        CREATE INDEX IF NOT EXISTS idx_user_numbers_number 
        ON user_numbers(number)
    """)

    c.execute("""
        CREATE INDEX IF NOT EXISTS idx_user_numbers_status 
        ON user_numbers(status)
    """)

    # ============================================================
    # FIX: Add ALL missing columns to existing tables
    # ============================================================

    # Users table columns
    columns_to_add_users = [
        ("username", "TEXT"),
        ("first_name", "TEXT"),
        ("status", "TEXT DEFAULT 'none'"),
        ("created_at", "TIMESTAMP DEFAULT CURRENT_TIMESTAMP")
    ]

    for col_name, col_type in columns_to_add_users:
        try:
            c.execute(f"ALTER TABLE users ADD COLUMN IF NOT EXISTS {col_name} {col_type}")
        except Exception as e:
            print(f"[DB INIT] users.{col_name}: {e}")

    # User numbers table columns
    columns_to_add_user_numbers = [
        ("assigned_at", "TIMESTAMP DEFAULT CURRENT_TIMESTAMP"),
        ("status", "TEXT DEFAULT 'active'"),
        ("is_primary", "BOOLEAN DEFAULT false")
    ]

    for col_name, col_type in columns_to_add_user_numbers:
        try:
            c.execute(f"ALTER TABLE user_numbers ADD COLUMN IF NOT EXISTS {col_name} {col_type}")
        except Exception as e:
            print(f"[DB INIT] user_numbers.{col_name}: {e}")

    conn.commit()
    conn.close()
    print("[DB INIT] ✅ Database initialized successfully")

# === USER OPERATIONS ===

def get_user(user_id):
    conn = get_db()
    c = conn.cursor()

    c.execute("SELECT * FROM users WHERE user_id = %s", (user_id,))
    user = c.fetchone()

    if user:
        # Get user's numbers
        c.execute("""
            SELECT * FROM user_numbers 
            WHERE user_id = %s AND status = 'active'
            ORDER BY is_primary DESC, assigned_at DESC
        """, (user_id,))
        numbers = c.fetchall()
        user = dict(user)
        user['numbers'] = [dict(n) for n in numbers] if numbers else []

    conn.close()
    return user if user else None

def save_user(user_id, username=None, first_name=None):
    conn = get_db()
    c = conn.cursor()

    c.execute("""
        INSERT INTO users (user_id, username, first_name) 
        VALUES (%s, %s, %s) 
        ON CONFLICT (user_id) DO UPDATE 
        SET username = EXCLUDED.username, 
            first_name = EXCLUDED.first_name
    """, (user_id, username, first_name))

    conn.commit()
    conn.close()

def assign_number_to_user(user_id, number, country_code, service):
    conn = get_db()
    c = conn.cursor()

    # Check if number is already assigned to ANY active user
    c.execute("""
        SELECT user_id FROM user_numbers 
        WHERE number = %s AND status = 'active'
    """, (number,))
    existing_owner = c.fetchone()

    if existing_owner:
        conn.close()
        if existing_owner['user_id'] == user_id:
            return False, "You already have this number"
        return False, "Number already assigned to another user"

    # Check current number count for user
    c.execute("""
        SELECT COUNT(*) as count FROM user_numbers 
        WHERE user_id = %s AND status = 'active'
    """, (user_id,))
    count = c.fetchone()['count']

    if count >= 3:
        conn.close()
        return False, "Maximum 3 numbers allowed"

    # Check if number previously belonged to this user (released)
    c.execute("""
        SELECT id FROM user_numbers 
        WHERE user_id = %s AND number = %s AND status = 'released'
    """, (user_id, number))
    existing = c.fetchone()

    if existing:
        # Reactivate the number
        c.execute("""
            UPDATE user_numbers 
            SET country_code = %s, service = %s, assigned_at = %s, status = 'active'
            WHERE id = %s
        """, (country_code, service, datetime.now(), existing['id']))
    else:
        # Check if this is the first number (make it primary)
        is_primary = (count == 0)

        # Insert new number
        c.execute("""
            INSERT INTO user_numbers (user_id, number, country_code, service, is_primary)
            VALUES (%s, %s, %s, %s, %s)
        """, (user_id, number, country_code, service, is_primary))

    # Update user status
    c.execute("""
        UPDATE users SET status = 'active' WHERE user_id = %s
    """, (user_id,))

    conn.commit()
    conn.close()
    return True, "Number assigned successfully"

def release_user_number(user_id, number=None):
    conn = get_db()
    c = conn.cursor()

    if number:
        # Release specific number
        c.execute("""
            UPDATE user_numbers 
            SET status = 'released' 
            WHERE user_id = %s AND number = %s AND status = 'active'
        """, (user_id, number))
    else:
        # Release all numbers
        c.execute("""
            UPDATE user_numbers 
            SET status = 'released' 
            WHERE user_id = %s AND status = 'active'
        """, (user_id,))

    # Check if user has any active numbers left
    c.execute("""
        SELECT COUNT(*) as count FROM user_numbers 
        WHERE user_id = %s AND status = 'active'
    """, (user_id,))
    count = c.fetchone()['count']

    if count == 0:
        c.execute("""
            UPDATE users SET status = 'none' WHERE user_id = %s
        """, (user_id,))

    conn.commit()
    conn.close()
    return True

def get_user_numbers(user_id):
    """Get all active numbers for a user"""
    conn = get_db()
    c = conn.cursor()

    c.execute("""
        SELECT * FROM user_numbers 
        WHERE user_id = %s AND status = 'active'
        ORDER BY is_primary DESC, assigned_at DESC
    """, (user_id,))

    numbers = c.fetchall()
    conn.close()
    return [dict(n) for n in numbers] if numbers else []

def get_user_by_number(number):
    """Get user by assigned number"""
    conn = get_db()
    c = conn.cursor()

    c.execute("""
        SELECT u.*, un.number, un.country_code, un.service 
        FROM users u
        JOIN user_numbers un ON u.user_id = un.user_id
        WHERE un.number = %s AND un.status = 'active'
    """, (number,))

    user = c.fetchone()
    conn.close()
    return dict(user) if user else None

# ============================================================
# FIX: get_all_users() - Use SELECT u.* to avoid column errors
# ============================================================
def get_all_users():
    """Get all users with their active numbers"""
    conn = get_db()
    c = conn.cursor()

    # Use u.* to get all user columns dynamically
    c.execute("""
        SELECT 
            u.*,
            COALESCE(
                array_remove(array_agg(un.number), NULL),
                '{}'
            ) as numbers,
            COALESCE(
                array_remove(array_agg(un.service), NULL),
                '{}'
            ) as services
        FROM users u
        LEFT JOIN user_numbers un 
            ON u.user_id = un.user_id 
            AND un.status = 'active'
        GROUP BY u.user_id
        ORDER BY COALESCE(u.created_at, CURRENT_TIMESTAMP) DESC
    """)

    users = c.fetchall()
    conn.close()
    return [dict(u) for u in users]

# === COMBO OPERATIONS ===

def add_combo(country_code, service, numbers_list):
    conn = get_db()
    c = conn.cursor()

    numbers_json = json.dumps(numbers_list)
    c.execute("""
        INSERT INTO combos (country_code, service, numbers) 
        VALUES (%s, %s, %s)
    """, (country_code, service, numbers_json))

    conn.commit()
    conn.close()

def get_combo(country_code, service):
    conn = get_db()
    c = conn.cursor()

    c.execute("""
        SELECT * FROM combos 
        WHERE country_code = %s AND service = %s 
        ORDER BY id DESC LIMIT 1
    """, (country_code, service))

    combo = c.fetchone()
    conn.close()
    return dict(combo) if combo else None

def pop_number_from_combo(country_code, service):
    conn = get_db()
    c = conn.cursor()

    combo = get_combo(country_code, service)
    if not combo:
        conn.close()
        return None

    numbers = json.loads(combo['numbers'])
    if not numbers:
        conn.close()
        return None

    number = numbers.pop(0)

    c.execute("""
        UPDATE combos SET numbers = %s WHERE id = %s
    """, (json.dumps(numbers), combo['id']))

    conn.commit()
    conn.close()
    return number

# === OTP OPERATIONS ===

def save_otp_log(user_id, number, service, otp_code, sender, message_body):
    conn = get_db()
    c = conn.cursor()

    # Save to processed OTPs (to avoid duplicates)
    c.execute("""
        INSERT INTO processed_otps (number, otp_code, received_at) 
        VALUES (%s, %s, %s) 
        ON CONFLICT (number, otp_code) DO NOTHING
    """, (number, otp_code, datetime.now()))

    # Save to OTP logs
    c.execute("""
        INSERT INTO otp_logs (user_id, number, service, otp_code, sender, message_body, received_at) 
        VALUES (%s, %s, %s, %s, %s, %s, %s)
    """, (user_id, number, service, otp_code, sender, message_body, datetime.now()))

    conn.commit()
    conn.close()

def is_otp_processed(number, otp_code):
    conn = get_db()
    c = conn.cursor()

    c.execute("""
        SELECT id FROM processed_otps 
        WHERE number = %s AND otp_code = %s
    """, (number, otp_code))

    result = c.fetchone()
    conn.close()
    return result is not None

# === MULTI-NUMBER OTP FUNCTIONS ===

def get_all_active_numbers():
    """Get all active numbers for OTP listening"""
    conn = get_db()
    c = conn.cursor()

    c.execute("""
        SELECT un.number, un.user_id, un.service, u.username
        FROM user_numbers un
        JOIN users u ON un.user_id = u.user_id
        WHERE un.status = 'active'
    """)

    numbers = c.fetchall()
    conn.close()
    return [dict(n) for n in numbers] if numbers else []

def set_primary_number(user_id, number):
    """Set a primary number for user"""
    conn = get_db()
    c = conn.cursor()

    # Verify the number belongs to user
    c.execute("""
        SELECT id FROM user_numbers 
        WHERE user_id = %s AND number = %s AND status = 'active'
    """, (user_id, number))

    if not c.fetchone():
        conn.close()
        return False, "Number not found or not active"

    # Remove primary from all numbers
    c.execute("""
        UPDATE user_numbers SET is_primary = false 
        WHERE user_id = %s
    """, (user_id,))

    # Set new primary
    c.execute("""
        UPDATE user_numbers SET is_primary = true 
        WHERE user_id = %s AND number = %s
    """, (user_id, number))

    conn.commit()
    conn.close()
    return True, "Primary number updated"

def delete_user(user_id):
    """Delete user and all associated data (CASCADE will handle numbers)"""
    conn = get_db()
    c = conn.cursor()

    c.execute("DELETE FROM users WHERE user_id = %s", (user_id,))

    conn.commit()
    conn.close()
    return True

# Initialize DB
init_db()

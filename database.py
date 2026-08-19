import sqlite3
from datetime import datetime

DB_NAME = "contest_bot.db"

def get_connection():
    return sqlite3.connect(DB_NAME)

def init_db():
    conn = get_connection()
    cursor = conn.cursor()
    
    # Таблица пользователей
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            reg_date TEXT,
            is_subscribed INTEGER DEFAULT 0
        )
    ''')
    
    # Таблица конкурсов
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS contests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            link TEXT,
            title TEXT,
            end_time TEXT,
            status TEXT DEFAULT 'active',
            participated INTEGER DEFAULT 0
        )
    ''')
    
    # Таблица настроек
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS settings (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            required_channel TEXT DEFAULT '',
            last_newsletter TEXT
        )
    ''')
    
    # Создаём настройки по умолчанию
    cursor.execute('SELECT COUNT(*) FROM settings')
    if cursor.fetchone()[0] == 0:
        cursor.execute('INSERT INTO settings (id, required_channel) VALUES (1, "")')
    
    conn.commit()
    conn.close()

# === ПОЛЬЗОВАТЕЛИ ===
def add_user(user_id, username):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('''
        INSERT OR IGNORE INTO users (user_id, username, reg_date, is_subscribed)
        VALUES (?, ?, ?, ?)
    ''', (user_id, username, datetime.now().isoformat(), 0))
    conn.commit()
    conn.close()

def get_user(user_id):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM users WHERE user_id = ?', (user_id,))
    user = cursor.fetchone()
    conn.close()
    return user

def update_subscription(user_id, status):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('UPDATE users SET is_subscribed = ? WHERE user_id = ?', (status, user_id))
    conn.commit()
    conn.close()

def get_all_users():
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT user_id FROM users')
    users = cursor.fetchall()
    conn.close()
    return [u[0] for u in users]

def get_users_count():
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT COUNT(*) FROM users')
    count = cursor.fetchone()[0]
    conn.close()
    return count

# === КОНКУРСЫ ===
def add_contest(user_id, link, title, end_time):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO contests (user_id, link, title, end_time)
        VALUES (?, ?, ?, ?)
    ''', (user_id, link, title, end_time))
    conn.commit()
    conn.close()

def get_active_contests(user_id):
    conn = get_connection()
    cursor = conn.cursor()
    # Используем localtime для правильного сравнения с местным временем
    cursor.execute('''
        SELECT * FROM contests 
        WHERE user_id = ? AND status = 'active' AND end_time > datetime('now', 'localtime')
        ORDER BY end_time
    ''', (user_id,))
    contests = cursor.fetchall()
    conn.close()
    return contests

def get_todays_contests(user_id):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('''
        SELECT * FROM contests 
        WHERE user_id = ? 
        AND status = 'active'
        AND date(end_time) = date('now', 'localtime')
        ORDER BY end_time
    ''', (user_id,))
    contests = cursor.fetchall()
    conn.close()
    return contests

def mark_participated(contest_id):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('UPDATE contests SET participated = 1 WHERE id = ?', (contest_id,))
    conn.commit()
    conn.close()

def delete_contest(contest_id):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('DELETE FROM contests WHERE id = ?', (contest_id,))
    conn.commit()
    conn.close()

def get_all_contests(user_id):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('''
        SELECT * FROM contests 
        WHERE user_id = ? 
        ORDER BY datetime(end_time) DESC
    ''', (user_id,))
    contests = cursor.fetchall()
    conn.close()
    return contests

# === НАСТРОЙКИ ===
def get_required_channel():
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT required_channel FROM settings WHERE id = 1')
    result = cursor.fetchone()
    conn.close()
    return result[0] if result else ""

def set_required_channel(channel):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('UPDATE settings SET required_channel = ? WHERE id = 1', (channel,))
    conn.commit()
    conn.close()

def get_last_newsletter():
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('SELECT last_newsletter FROM settings WHERE id = 1')
    result = cursor.fetchone()
    conn.close()
    return result[0] if result else None

def set_last_newsletter(date):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('UPDATE settings SET last_newsletter = ? WHERE id = 1', (date,))
    conn.commit()
    conn.close()

# === ПРОВЕРКА ДУБЛИКАТОВ ===
def check_duplicate(user_id, link):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('''
        SELECT id, title, end_time, status 
        FROM contests 
        WHERE user_id = ? AND link = ?
        ORDER BY datetime(end_time) DESC
        LIMIT 1
    ''', (user_id, link))
    contest = cursor.fetchone()
    conn.close()
    return contest

def get_time_left(end_time_str):
    try:
        end_time = datetime.strptime(end_time_str, "%Y-%m-%d %H:%M")
        now = datetime.now()
        diff = end_time - now
        
        if diff.total_seconds() <= 0:
            return "закончился"
        
        days = diff.days
        hours = diff.seconds // 3600
        minutes = (diff.seconds % 3600) // 60
        
        parts = []
        if days > 0:
            parts.append(f"{days}д")
        if hours > 0:
            parts.append(f"{hours}ч")
        if minutes > 0:
            parts.append(f"{minutes}м")
        
        return " ".join(parts) if parts else "менее минуты"
    except:
        return "неизвестно"

# === ОЧИСТКА СТАРЫХ КОНКУРСОВ (ОПЦИОНАЛЬНО) ===
def clean_expired_contests():
    """Удаляет конкурсы, которые закончились больше 30 дней назад"""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute('''
        DELETE FROM contests 
        WHERE status = 'active' 
        AND datetime(end_time) < datetime('now', 'localtime', '-30 days')
    ''')
    deleted = cursor.rowcount
    conn.commit()
    conn.close()
    return deleted

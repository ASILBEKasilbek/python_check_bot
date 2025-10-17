import sqlite3
from config.settings import DB_PATH

def init_db():
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                first_name TEXT NOT NULL,
                last_name TEXT NOT NULL,
                phone_number TEXT NOT NULL,
                coins INTEGER DEFAULT 0,
                language TEXT DEFAULT 'uz'
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS problems (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                text TEXT NOT NULL,
                image_path TEXT,
                difficulty TEXT NOT NULL,
                category TEXT NOT NULL,
                deadline TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                scheduled_at TIMESTAMP
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS submissions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                problem_id INTEGER,
                photo_path TEXT NOT NULL,
                status TEXT DEFAULT 'pending',
                reviewed_at TIMESTAMP,
                feedback TEXT,
                FOREIGN KEY (user_id) REFERENCES users(user_id),
                FOREIGN KEY (problem_id) REFERENCES problems(id)
            )
        """)
        conn.commit()
    except sqlite3.Error as e:
        print(f"Database initialization error: {e}")
    finally:
        conn.close()
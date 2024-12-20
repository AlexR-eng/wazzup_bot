import sqlite3

def create_database():
    conn = sqlite3.connect('database.db')
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS user_threads (
            chat_id TEXT PRIMARY KEY,
            thread_id TEXT NOT NULL
        )
    ''')
    conn.commit()
    conn.close()
    print("База данных успешно создана или уже существует.")

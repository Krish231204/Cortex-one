import sqlite3

conn = sqlite3.connect('chat_history.db')
c = conn.cursor()

c.execute('''
    CREATE TABLE IF NOT EXISTS chats (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        session_id TEXT,
        user_message TEXT,
        response TEXT,
        timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
        session_name TEXT
    )
''')

conn.commit()
conn.close()
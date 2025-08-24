import sqlite3

conn = sqlite3.connect('chat_history.db')
c = conn.cursor()

# Show recent rows with session_id
rows = c.execute("SELECT id, user_message, bot_response, session_id FROM chats ORDER BY id DESC LIMIT 10").fetchall()

for row in rows:
    print(row)

conn.close()

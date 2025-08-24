# all_sessions_debug.py
import sqlite3

conn = sqlite3.connect('chat_history.db')
c = conn.cursor()

# View raw entries
c.execute("SELECT session_id, session_name, user_message, timestamp FROM chats ORDER BY timestamp DESC")
rows = c.fetchall()
conn.close()

print("\n--- All Chats (with session names) ---\n")
for row in rows:
    print(f"Session: {row[0]}\nName: {row[1]}\nMsg: {row[2]}\nTime: {row[3]}\n")
from calendar import c
from flask import Flask, render_template, request, jsonify,session,redirect
from openai import OpenAI
import openai
import os
from dotenv import load_dotenv
import sqlite3  # for database handling
from datetime import datetime  # to store timestamps
import uuid



app = Flask(__name__)
app.secret_key = '231204'  # Can be any random string for now
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

@app.route('/')
def home():
    if 'session_id' not in session:
        session['session_id'] = str(uuid.uuid4())
        session_name = generate_session_title("New chat started")
        session['session_name'] = session_name

        conn = sqlite3.connect('chat_history.db')
        c = conn.cursor()
        c.execute("""
            INSERT INTO chats (session_id, user_message, response, session_name)
            VALUES (?, ?, ?, ?)
        """, (session['session_id'], "", "", session_name))
        conn.commit()
        conn.close()

    conn = sqlite3.connect('chat_history.db')
    c = conn.cursor()
    c.execute("""
        SELECT DISTINCT session_id, session_name, MIN(timestamp)
        FROM chats
        WHERE session_name IS NOT NULL
        GROUP BY session_id
        ORDER BY MIN(timestamp) DESC
    """)
    sessions = c.fetchall()
    conn.close()

    return render_template('chat.html', sessions=sessions)

@app.route('/new')
def new_chat():
    session['session_id'] = str(uuid.uuid4())
    session.pop('session_name', None)
    return redirect('/')



@app.route('/chat', methods=['POST'])
def chat():
    user_message = request.json.get('message')
    response = generate_response(user_message)

    # Ensure session_id exists
    if 'session_id' not in session:
        session['session_id'] = str(uuid.uuid4())

    conn = sqlite3.connect('chat_history.db')
    c = conn.cursor()

    # Check number of messages in this session
    c.execute("SELECT COUNT(*) FROM chats WHERE session_id = ?", (session['session_id'],))
    count = c.fetchone()[0]

    session_name = session.get('session_name')

    if count == 0:
        # Generate and save new session name
        session_name = generate_session_title(user_message)
        session['session_name'] = session_name
        c.execute("INSERT INTO chats (session_id, user_message, response, session_name) VALUES (?, ?, ?, ?)",
                  (session['session_id'], user_message, response, session_name))
    else:
        # Reuse session_name if not already set in DB
        if not session_name:
            c.execute("SELECT session_name FROM chats WHERE session_id = ? AND session_name IS NOT NULL", (session['session_id'],))
            row = c.fetchone()
            if row:
                session_name = row[0]
                session['session_name'] = session_name
        c.execute("INSERT INTO chats (session_id, user_message, response, session_name) VALUES (?, ?, ?, ?)",
          (session['session_id'], user_message, response, session_name))
        #c.execute("INSERT INTO chats (session_id, user_message, response) VALUES (?, ?, ?)",
        #          (session['session_id'], user_message, response)) 

    print("Saving to DB:", user_message, response, session['session_id'], session_name)

    conn.commit()
    conn.close()

    return jsonify({'reply': response})






def init_db():
    conn = sqlite3.connect('chat_history.db')  # creates file if it doesn’t exist
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS chats (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_message TEXT NOT NULL,
            response TEXT NOT NULL,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            session_id TEXT,
            session_name TEXT
        )
    ''')
    conn.commit()
    conn.close()
@app.route('/session/<session_id>')
def load_session(session_id):
    conn = sqlite3.connect('chat_history.db')
    c = conn.cursor()
    
    # Fetch messages for this session
    c.execute("SELECT user_message, response FROM chats WHERE session_id = ? ORDER BY timestamp", (session_id,))
    chats = c.fetchall()
    
    # Fetch all sessions for sidebar
    c.execute("""
        SELECT DISTINCT session_id, session_name, MIN(timestamp)
        FROM chats
        WHERE session_name IS NOT NULL
        GROUP BY session_id
        ORDER BY MIN(timestamp) DESC
    """)
    sessions = c.fetchall()

    conn.close()

    # Save the current session in memory
    session['session_id'] = session_id

    # Pass both chats and sessions to the template
    return render_template('chat.html', chats=chats, sessions=sessions)

def generate_session_title(user_input):
    try:
        completion = client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[
                {"role": "system", "content": "Generate a short, clear title (4-5 words max) for the following user_message."},
                {"role": "user", "content": user_input}
            ],
            max_tokens=10,
            temperature=0.5
        )
        return completion.choices[0].message.content.strip()
    except Exception as e:
        return "New Chat"

"""
def get_all_sessions():
    conn = sqlite3.connect('chat_history.db')
    c = conn.cursor()
    c.execute(""""""
        SELECT DISTINCT session_id, session_name, MIN(timestamp)
        FROM chats
        WHERE session_name IS NOT NULL
        GROUP BY session_id
        ORDER BY MIN(timestamp) DESC"""""")
    sessions = c.fetchall()
    conn.close()
    return sessions

"""
def generate_response(message):
    try:
        completion = client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[
                {"role": "system", "content": "You are a helpful assistant."},
                {"role": "user", "content": message}
            ]
        )
        reply = completion.choices[0].message.content.strip()
        return reply
    except Exception as e:
        return f"Error: {str(e)}"

if __name__ == '__main__':
    init_db()  # ← call it here!
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))

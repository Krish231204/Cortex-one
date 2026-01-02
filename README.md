# CortexOne 🧠

CortexOne is a full-stack AI chat assistant built using **Flask** and the **OpenAI API**.  
It supports **session-based conversations** with persistent chat history stored in **SQLite**, similar to modern ChatGPT-style applications.

🌐 **Live Demo:** https://cortex-one-wep1.onrender.com/chat_ui

> ⚠️ Note: The app may take a few seconds to load initially due to Render free-tier cold start.

---

## ✨ Key Features
- AI-powered chat using OpenAI API
- Session-based conversations (multiple chats)
- Automatic session title generation
- Persistent chat history using SQLite
- Sidebar to switch between previous sessions
- Clean and minimal ChatGPT-style UI

---

## 🛠️ Tech Stack
- **Backend:** Python, Flask  
- **AI:** OpenAI API  
- **Database:** SQLite  
- **Frontend:** HTML, CSS, JavaScript  
- **Deployment:** Render  

---

## 📂 Project Structure
CortexOne/
│── app.py
│── chat_history.db
│── templates/
│   └── chat.html
│── static/
│   └── style.css
│── .env
│── requirements.txt
│── README.md

---

## ⚙️ Run Locally

### 1️⃣ Clone the repository

git clone https://github.com/Krish231204/Cortex-one.git
cd Cortex-one

(Optional) Create virtual environment

python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate

install dependencies

pip install -r requirements.txt

Create .env file

OPENAI_API_KEY=your_openai_api_key_here

Run the application

python app.py

Open http://localhost:5050 in your browser.


📌 Current Status

✔ Core functionality completed
✔ Stable & deployed
🔧 UI refinements and performance improvements planned

⸻

🚀 Future Improvements
	•	Conversation context memory
	•	User authentication
	•	Export chat history
	•	Improved UI animations
	•	Rate limiting & security hardening

⸻

📄 License

This project is licensed under the MIT License.

📌 Replace `https://cortex-one-wep1.onrender.com/chat_ui` with your actual Render URL.

---

# ✅ 2️⃣ `.gitignore` (CRITICAL — DO THIS)

Create `.gitignore` with:

```gitignore
.env
__pycache__/
*.pyc
venv/
chat_history.db

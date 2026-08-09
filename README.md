# CortexOne 🧠

A private, streaming AI chat assistant. Flask + Postgres, deployed as a single
Vercel Function.

Every conversation belongs to an account. Nobody can read anybody else's.

---

## ⚠️ Read this first if you ran the old version

The previous build had three problems that need action, not just a code change:

1. **Rotate your OpenAI key.** The old `app.py` ran
   `print("Loaded API Key:", os.getenv("OPENAI_API_KEY"))` on every boot, which
   wrote the full key into Render's log stream. The key was never committed to
   git — the whole history was scanned and it is clean — but assume anything in
   those logs is exposed. Generate a new key and delete the old one.
2. **Every visitor could read every conversation.** There were no accounts, and
   the sidebar query had no owner filter, so `/chat_ui` listed all sessions in
   the database to anyone who opened the site and `/session/<id>` served any of
   them. If the Render deployment was public, treat everything in it as public.
3. **`chat_history.db` was committed** despite being listed in `.gitignore` —
   the rule was added after the file, so it did nothing. It is untracked now,
   and the local copy is kept as `chat_history.db.local` for the migration. The
   file still exists in older commits; see [Scrubbing git history](#scrubbing-git-history).

---

## ✨ What it does

- Email + password accounts; conversations are private to the account that owns them
- **The assistant remembers the conversation** — prior turns are replayed to the
  model within a token budget. The old build sent only the current message, so
  it had no memory of anything said earlier in the same chat.
- **Streamed replies** — text appears as it is generated instead of after a wait
- Auto-generated conversation titles, produced *concurrently* with the reply
  rather than before it, so the first message is no longer twice as slow
- Rename and delete conversations
- Markdown rendering with fenced code blocks, escaped safely

---

## 🛠️ Stack

| Layer | Choice | Why |
| --- | --- | --- |
| Web | Flask 3 (WSGI) | Vercel's Python runtime loads a top-level `app` directly |
| Database | Neon Postgres | Serverless-friendly, real persistence, connection pooling built in |
| Driver | psycopg 3 | Pool reused across warm invocations |
| Hosting | Vercel Functions | No idle spin-down like Render's free tier; 300s max duration on Hobby with Fluid compute |
| Auth | Flask signed cookies + scrypt | Stateless, so it survives serverless cold starts |

---

## 🚀 Setup

### 1. Create the database

Sign up at [neon.com](https://neon.com), create a project, and copy the
**pooled** connection string — the host contains `-pooler`. Use that one. The
direct endpoint opens a new connection per invocation and will exhaust the
connection limit under any real traffic.

### 2. Configure

```bash
cp .env.example .env
python -c "import secrets; print(secrets.token_urlsafe(48))"   # SECRET_KEY
```

Fill in `SECRET_KEY`, `DATABASE_URL`, and your **rotated** `OPENAI_API_KEY`.

### 3. Install and create the schema

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python scripts/init_db.py
```

### 4. Run

```bash
python app.py
```

Open <http://localhost:5050>, create an account, and start a chat.

For local development set `FLASK_ENV=development` in `.env` — it relaxes the
`Secure` cookie flag so sessions work over plain HTTP, and mints a throwaway
`SECRET_KEY` if you have not set one.

---

## 📦 Migrating the old SQLite history

The old data has no owner, so it is assigned to one account. Register through
the web UI first, then:

```bash
python scripts/migrate_sqlite_to_postgres.py --email you@example.com --dry-run
```

Drop `--dry-run` to write. Each old row becomes a user message and an assistant
message with the original timestamp preserved; old `session_id`s map to
conversations. Re-running skips anything already imported.

---

## ☁️ Deploying to Vercel

```bash
npm i -g vercel
vercel link
vercel --prod
```

Set `SECRET_KEY`, `DATABASE_URL`, and `OPENAI_API_KEY` under **Project Settings
→ Environment Variables** before the first deploy. The app raises `ConfigError`
at startup rather than booting with a guessable secret, so a missing variable
fails loudly instead of silently.

`vercel.json` sets `maxDuration: 300` on `app.py`. Vercel resolves the whole
Flask app to that one entrypoint, so the whole app is one function.

**On cold starts:** Vercel does not idle-stop your app the way Render's free
tier does after 15 minutes, so the ~50s wake-up is gone. A genuine cold start
still costs a few hundred milliseconds for the Python import plus the first
database connection; every warm invocation reuses both.

---

## 🔐 What the rebuild fixed

| Issue | Before | Now |
| --- | --- | --- |
| Cross-user data access | `/session/<id>` served any conversation to anyone | Every query filtered by `user_id` in SQL; foreign ids return 404 |
| Session forgery | `app.secret_key = '231204'` | Required from env; production refuses to boot without it |
| API key exposure | Printed to logs on every boot | Never logged |
| XSS | `chatBox.innerHTML += '<span>' + userMessage + '</span>'` | User text via `textContent`; model output escaped before a fixed tag set is applied; CSP without `unsafe-inline` |
| CSRF | No protection | Token enforced globally on every non-idempotent request |
| Password storage | No accounts at all | scrypt via Werkzeug |
| Committed database | `chat_history.db` tracked in git | Untracked; `.gitignore` corrected |
| Error leakage | `return f"Error: {str(e)}"` sent driver and API errors to the browser | Logged server-side, generic message to the client |
| Production server | `app.run()` (Werkzeug dev server) | Vercel's runtime; dev server is local-only |

Redirects through `?next=` are restricted to same-site paths, login failures are
indistinguishable between a wrong password and an unknown email, and there is a
per-user hourly message cap (`RATE_LIMIT_PER_HOUR`).

---

## 🧪 Tests

The suite covers the vulnerabilities above as regressions — cross-user reads,
writes, renames and deletes; CSRF; escaping; and the conversation-memory and
streaming behaviour.

```bash
docker run -d --name cortexone-pg -e POSTGRES_PASSWORD=devpass -e POSTGRES_DB=cortexone -p 55432:5432 postgres:16-alpine
```

```bash
TEST_DATABASE_URL=postgresql://postgres:devpass@localhost:55432/cortexone python -m pytest tests -q
```

Tests use their own database and drop the tables between runs — do not point
`TEST_DATABASE_URL` at anything you care about.

---

## 🧩 Layout

```
app.py                    Vercel entrypoint; exposes `app`
cortexone/
  config.py               Env-driven config; fails fast on missing secrets
  db.py                   psycopg pool tuned for PgBouncer transaction mode
  models.py               Data access — every query scoped by user_id
  security.py             Passwords, sessions, CSRF, rate limiting
  llm.py                  Context building, streaming, titles
  blueprints/auth.py      Register / login / logout
  blueprints/chat.py      Pages, conversation CRUD, SSE endpoint
migrations/001_init.sql   Schema
scripts/                  init_db, SQLite migration
templates/  static/       UI
tests/                    Security and behaviour tests
```

---

## ⚙️ Configuration

| Variable | Default | Notes |
| --- | --- | --- |
| `SECRET_KEY` | — | Required in production |
| `DATABASE_URL` | — | Required; use the pooled Neon endpoint |
| `OPENAI_API_KEY` | — | Required |
| `OPENAI_BASE_URL` | unset | For OpenAI-compatible proxies |
| `OPENAI_MODEL` | `gpt-5.6-sol` | **Verify against your account's model list** — OpenAI's lineup changes often and a stale id returns a 404 |
| `OPENAI_TITLE_MODEL` | `gpt-5.6-luna` | Same caveat |
| `MAX_CONTEXT_MESSAGES` | `20` | Prior turns replayed to the model |
| `MAX_CONTEXT_CHARS` | `24000` | Character budget for that history |
| `RATE_LIMIT_PER_HOUR` | `120` | Per user; `0` disables |
| `DB_POOL_MAX` | `5` | Connections per warm instance |
| `FLASK_ENV` | `production` | `development` relaxes cookie security for local HTTP |

---

## Scrubbing git history

`chat_history.db` is untracked now, but older commits still contain it. It holds
37 of your own test messages and no credentials, so this is optional. To remove
it anyway, with [git-filter-repo](https://github.com/newren/git-filter-repo):

```bash
git filter-repo --invert-paths --path chat_history.db --force
```

That rewrites every commit hash, so force-push and re-clone anywhere else you
have the repo.

---

## 📄 License

MIT — see [LICENSE](LICENSE).

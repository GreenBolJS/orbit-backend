# 🪐 Orbit Backend

A FastAPI-powered job/internship alert agent that uses Gemini AI to find and score job postings relevant to your profile, and notifies you via Telegram.

---

## How it works

1. You set up your profile (skills, roles, locations, experience level)
2. Orbit asks Gemini to generate targeted Google search queries for you
3. Serper runs those queries and collects job listings
4. Gemini scores each listing 1–10 for relevance to your profile
5. Matches above the threshold are saved and (if high-scoring) pushed to your Telegram

The pipeline runs automatically every 6 hours (configurable).

---

## Setup

### 1. Clone & install

```bash
cd orbit-backend
python -m venv venv
source venv/bin/activate   # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

### 2. Copy and fill in environment variables

```bash
cp .env.example .env
```

Open `.env` and fill in all the keys (see sections below for how to get each one).

### 3. Create Supabase tables

1. Go to [supabase.com](https://supabase.com) and create a free project
2. Open **SQL Editor → New Query**
3. Paste the contents of `schema.sql` and click **Run**
4. Copy your project URL and `anon` key from **Settings → API** into `.env`

### 4. Get a Gemini API key

1. Go to [aistudio.google.com](https://aistudio.google.com)
2. Click **"Get API Key"** → **Create API Key**
3. Copy it into `GEMINI_API_KEY` in your `.env`

**Free tier limits:** 15 requests/minute, 1 million tokens/day — more than enough for this project.

### 5. Get a Serper API key

1. Go to [serper.dev](https://serper.dev) and sign up
2. Free tier gives you **2,500 search queries/month**
3. Copy your API key into `SERPER_API_KEY` in your `.env`

### 6. Create a Telegram bot

1. Open Telegram and search for **@BotFather**
2. Send `/newbot` and follow the prompts
3. Copy the bot token into `TELEGRAM_BOT_TOKEN` in your `.env`
4. Start a conversation with your new bot (send it any message)
5. Visit `https://api.telegram.org/bot<YOUR_TOKEN>/getUpdates` in your browser
6. Find `"chat": {"id": XXXXXXXX}` — that number is your `TELEGRAM_CHAT_ID`

### 7. Run it

```bash
uvicorn main:app --reload --port 8000
```

Visit [http://localhost:8000/docs](http://localhost:8000/docs) for the interactive API docs.

---

## API Reference

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/health` | Health check + last run time |
| `POST` | `/profile` | Save/update your job profile |
| `GET` | `/profile` | Get current profile |
| `GET` | `/matches` | List all non-dismissed matches |
| `GET` | `/matches?min_score=8` | Filter by minimum score |
| `POST` | `/matches/dismiss/{id}` | Dismiss a match |
| `DELETE` | `/matches/clear` | Delete all matches |
| `POST` | `/run-agent` | Manually trigger the pipeline |

---

## Configuration

All config lives in `.env`:

| Variable | Default | Description |
|----------|---------|-------------|
| `AGENT_INTERVAL_HOURS` | `6` | How often the pipeline runs |
| `MIN_SCORE_TO_SAVE` | `6` | Minimum score to save a match |
| `MIN_SCORE_TO_NOTIFY` | `8` | Minimum score to send Telegram alert |
| `FRONTEND_URL` | `http://localhost:5173` | Your frontend URL (for CORS) |

---

## Deploy to Railway

1. Push this folder to a GitHub repo
2. Go to [railway.app](https://railway.app) → **New Project → Deploy from GitHub**
3. Select your repo
4. Add all environment variables from `.env` in the **Variables** tab
5. Railway will auto-detect Python and deploy

Railway will set a `PORT` env var automatically — uvicorn reads it via the start command. Add this to Railway's **Start Command**:

```
uvicorn main:app --host 0.0.0.0 --port $PORT
```

---

## File Structure

```
orbit-backend/
├── main.py          # FastAPI app, CORS, scheduler, all routes
├── agent.py         # Core pipeline: query → search → score → save → notify
├── database.py      # Supabase CRUD helpers
├── notifier.py      # Telegram message sender
├── schemas.py       # Pydantic v2 request/response models
├── schema.sql       # SQL to create Supabase tables
├── .env.example     # All required environment variables
├── requirements.txt
└── README.md
```

---

## Troubleshooting

**Pipeline finds 0 results:** Check your Serper API key is valid and you have remaining quota.

**Gemini errors:** Make sure `GEMINI_API_KEY` is set. If you hit rate limits, increase the sleep delay in `agent.py` (`asyncio.sleep(0.3)` → `asyncio.sleep(1.0)`).

**Telegram not sending:** Double-check the bot token and chat ID. Make sure you've sent the bot at least one message first.

**Supabase errors:** Confirm you ran the `schema.sql` and that your `SUPABASE_URL` doesn't have a trailing slash.

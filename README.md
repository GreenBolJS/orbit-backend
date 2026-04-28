# orbit-backend

FastAPI agentic backend for Orbit — a personal career intelligence agent that monitors job markets and delivers personalized opportunities.

🌐 **API:** [orbit-backend-production-26a0.up.railway.app](https://orbit-backend-production-26a0.up.railway.app/docs)

---

## The Idea

Every day, millions of students and job seekers chat with AI tools like ChatGPT and Claude. They describe their skills, their goals, the kind of work they want. And then — nothing. The conversation ends, the context disappears, and tomorrow they're back to manually refreshing Naukri and LinkedIn.

The insight behind Orbit is simple: **your AI conversations already contain everything a job search agent needs to know about you.** The roles you mention. The skills you list. The companies you're curious about. The locations you prefer. It's all there — just locked inside a chat window that forgets everything the moment you close it.

Orbit fixes this. It gives your AI conversations persistent memory, and puts that memory to work.

---

## The Problem With Existing Tools

- **Job boards are passive** — you have to go to them, search, filter, repeat every day
- **Alerts are generic** — keyword-based, not contextually aware of your actual profile
- **AI tools are stateless** — ChatGPT doesn't remember what you told it last week
- **The gap between "I want a job" and "here are relevant jobs" requires manual work every single day**

Orbit closes that gap entirely. Once set up, it requires zero ongoing effort.

---

## How Orbit Thinks Differently

Traditional job alerts:
```
User sets keywords → Alert fires on keyword match → User gets flooded with irrelevant results
```

Orbit:
```
User chats naturally with AI about their goals
        ↓
Chrome extension passively extracts career intent
        ↓
LLM builds a rich profile: roles + skills + locations + level
        ↓
Agent generates targeted search queries from that profile
        ↓
Each result scored 1-10 with a specific reason why it matches
        ↓
Only genuinely relevant matches reach the user
```

The difference is context. A keyword match for "Python engineer" treats a senior backend role and a fresher ML internship identically. Orbit knows you're a BTech student at IIT Roorkee looking for summer 2026 internships in ML — and scores accordingly.

---

## What This Does

This is the brain of Orbit. It runs a background pipeline every 6 hours that:
1. Loads your career profile from Supabase
2. Generates targeted search queries using Groq (Llama 3.3)
3. Searches 15+ job sites via Serper API
4. Scores each listing for relevance using LLM
5. Saves high-score matches to the database
6. Sends Telegram notifications for the best matches

It also exposes a `/chat-sync` endpoint that the Chrome extension uses to automatically update your profile from AI conversations.

---

## Architecture

```
┌─────────────────┐     ┌──────────────────┐
│  Chrome          │    │   Cloudflare     │
│  Extension       │    │   Pages          │
│  (content.js)    │    │   (React UI)     │
└────────┬────────┘     └────────┬─────────┘
         │                       │
         │ POST /chat-sync       │ GET /matches
         │                       │
         ▼                       ▼
┌─────────────────────────────────────────┐
│           orbit-backend                 │
│           (Railway)                     │
│                                         │
│  ┌─────────────┐   ┌─────────────────┐  │
│  │ APScheduler │   │  /chat-sync     │  │
│  │ (6hr cron)  │   │  /run-agent     │  │
│  └──────┬──────┘   └────────┬────────┘  │
│         │                   │           │
│         └─────────┬─────────┘           │
│                   ▼                     │
│           agent.py pipeline             │
│    1. Load profile from Supabase        │
│    2. Generate queries via Groq         │
│    3. Search via Serper API             │
│    4. Score results via Groq            │
│    5. Save to Supabase                  │
│    6. Notify via Telegram               │
└─────────────────────────────────────────┘
         │                   │
         ▼                   ▼
┌──────────────┐    ┌──────────────────┐
│   Supabase   │    │  Telegram Bot    │
│  PostgreSQL  │    │  Notifications   │
└──────────────┘    └──────────────────┘
```

---

## Tech Stack

- **FastAPI** — REST API framework
- **Groq API** (Llama 3.3 70B) — query generation + relevance scoring
- **Supabase** (PostgreSQL) — profiles and matches storage
- **Serper API** — Google search for job listings
- **Telegram Bot API** — push notifications
- **APScheduler** — background cron jobs
- **Railway** — deployment and hosting

---

## Setup

### 1. Clone and install

```bash
git clone https://github.com/GreenBolJS/orbit-backend
cd orbit-backend

python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

### 2. Get your API keys

| Key | Where to get it |
|---|---|
| `GROQ_API_KEY` | [console.groq.com](https://console.groq.com) → API Keys → Create (free) |
| `SERPER_API_KEY` | [serper.dev](https://serper.dev) → Sign up → Dashboard (2500 free queries/month) |
| `SUPABASE_URL` + `SUPABASE_KEY` | [supabase.com](https://supabase.com) → New project → Settings → API |
| `TELEGRAM_BOT_TOKEN` | Message **@BotFather** on Telegram → `/newbot` → copy token |
| `TELEGRAM_CHAT_ID` | Message your bot once → open `https://api.telegram.org/bot{TOKEN}/getUpdates` → copy `id` from `chat` |

### 3. Create `.env`

```
GROQ_API_KEY=
SERPER_API_KEY=
SUPABASE_URL=
SUPABASE_KEY=
TELEGRAM_BOT_TOKEN=
TELEGRAM_CHAT_ID=
FRONTEND_URL=http://localhost:8080
PORT=8000
AGENT_INTERVAL_HOURS=6
MIN_SCORE_TO_SAVE=6
MIN_SCORE_TO_NOTIFY=8
```

### 4. Set up Supabase tables

Go to Supabase → SQL Editor → run:

```sql
create table profiles (
  id uuid primary key default gen_random_uuid(),
  skills text[], roles text[], locations text[],
  companies text[], experience_level text,
  updated_at timestamptz default now()
);

create table matches (
  id uuid primary key default gen_random_uuid(),
  title text, company text, url text unique,
  score integer, reason text, query text,
  dismissed boolean default false,
  found_at timestamptz default now()
);

create table feedback (
  id uuid primary key default gen_random_uuid(),
  match_id uuid references matches(id),
  action text,
  created_at timestamptz default now()
);
```

### 5. Start the server

```bash
uvicorn main:app --reload
```

Open `http://localhost:8000/docs` to test all endpoints interactively.

---

## API Endpoints

| Method | Endpoint | Description |
|---|---|---|
| POST | `/profile` | Save user profile |
| GET | `/profile` | Get current profile |
| GET | `/matches` | Get all job matches |
| POST | `/matches/dismiss/{id}` | Dismiss a match |
| DELETE | `/matches/clear` | Clear all matches |
| POST | `/run-agent` | Manually trigger pipeline |
| POST | `/chat-sync` | Sync from AI conversation |
| GET | `/health` | Health check |

---

## File Structure

```
orbit-backend/
├── main.py          # FastAPI app + all endpoints
├── agent.py         # Core pipeline logic
├── database.py      # Supabase CRUD helpers
├── notifier.py      # Telegram notifications
├── schemas.py       # Pydantic models
├── requirements.txt
└── runtime.txt      # Python version for Railway
```

---

## Deployment

Deployed on Railway. Auto-deploys on push to main branch.

To deploy your own instance:
1. Push this repo to GitHub
2. Go to [railway.app](https://railway.app) → New Project → Deploy from GitHub
3. Add all environment variables from your `.env`
4. Add `PORT=8000` in Railway variables
5. Railway handles the rest — generates a public URL automatically

---

## Part of Orbit

| Repo | Description |
|---|---|
| **orbit-backend** | This repo — FastAPI pipeline |
| [orbit-your-career-compass](https://github.com/GreenBolJS/orbit-your-career-compass) | React dashboard |
| [orbit_sync_extension](https://github.com/GreenBolJS/orbit_sync_extension) | Chrome extension |

---

**Daksh Chawla** — BTech, IIT Roorkee · [GitHub](https://github.com/GreenBolJS)

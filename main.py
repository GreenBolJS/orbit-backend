import os
import logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from dotenv import load_dotenv
from supabase import create_client

import database
import agent
from schemas import (
    ProfileCreate,
    ProfileResponse,
    MatchResponse,
    RunAgentResponse,
    HealthResponse,
    DismissResponse,
    ChatSyncRequest,
    ChatSyncResponse,
)

load_dotenv()

# ─── Supabase ───────────────────────────────────────────────────────────────────

SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "")
supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

# ─── Logging ────────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("orbit")

# ─── Config ─────────────────────────────────────────────────────────────────────

FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:5173")
AGENT_INTERVAL_HOURS = int(os.getenv("AGENT_INTERVAL_HOURS", "6"))

ALLOWED_ORIGINS = [
    "http://localhost:5173",
    "http://localhost:3000",
    "http://localhost:8080",
    "https://orbit-your-career-compass.daksh25chawla.workers.dev",
    FRONTEND_URL,
]

# ─── Scheduler ───────────────────────────────────────────────────────────────────

scheduler = AsyncIOScheduler()


async def scheduled_run():
    logger.info(f"[Orbit] Scheduled run triggered at {datetime.now(timezone.utc).isoformat()}")
    new_matches = await agent.run_pipeline()
    logger.info(f"[Orbit] Scheduled run found {new_matches} new matches")


# ─── Lifespan ────────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    scheduler.add_job(
        scheduled_run,
        "interval",
        hours=AGENT_INTERVAL_HOURS,
        id="orbit_pipeline",
        replace_existing=True,
    )
    scheduler.start()
    logger.info(f"[Orbit] Scheduler started — running every {AGENT_INTERVAL_HOURS} hours")
    yield
    # Shutdown
    scheduler.shutdown(wait=False)
    logger.info("[Orbit] Scheduler stopped")


# ─── App ─────────────────────────────────────────────────────────────────────────

app = FastAPI(
    title="Orbit API",
    description="Job/internship alert agent backend",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ─── Routes ──────────────────────────────────────────────────────────────────────

@app.get("/health", response_model=HealthResponse)
async def health():
    return HealthResponse(
        status="ok",
        agent_status="active" if scheduler.running else "stopped",
        last_run=agent.get_last_run(),
    )


@app.post("/profile", response_model=ProfileResponse)
async def create_profile(body: ProfileCreate):
    try:
        saved = database.upsert_profile(body.model_dump())
        if not saved:
            raise HTTPException(status_code=500, detail="Failed to save profile")
        return ProfileResponse(**saved)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[Orbit] /profile POST error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/profile", response_model=ProfileResponse)
async def read_profile():
    profile = database.get_profile()
    if not profile:
        raise HTTPException(status_code=404, detail="No profile found")
    return ProfileResponse(**profile)


@app.get("/matches", response_model=list[MatchResponse])
async def list_matches(min_score: int = Query(default=0, ge=0, le=10)):
    try:
        matches = database.get_matches(min_score=min_score)
        return [MatchResponse(**m) for m in matches]
    except Exception as e:
        logger.error(f"[Orbit] /matches GET error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/matches/dismiss/{match_id}", response_model=DismissResponse)
async def dismiss_match(match_id: str):
    try:
        success = database.dismiss_match(match_id)
        if not success:
            raise HTTPException(status_code=404, detail="Match not found")
        return DismissResponse(success=True, message="Match dismissed")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[Orbit] /matches/dismiss error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.delete("/matches/clear")
async def clear_matches():
    try:
        supabase.table("matches").delete().neq("id", "00000000-0000-0000-0000-000000000000").execute()
        return {"message": "All matches cleared", "deleted": true}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/chat-sync", response_model=ChatSyncResponse)
async def chat_sync(body: ChatSyncRequest):
    try:
        result = await agent.sync_from_conversation(body.messages, body.source)
        return ChatSyncResponse(**result)
    except Exception as e:
        logger.error(f"[Orbit] /chat-sync error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/run-agent", response_model=RunAgentResponse)
async def run_agent():
    try:
        new_matches = await agent.run_pipeline()
        return RunAgentResponse(
            new_matches=new_matches,
            message=f"Pipeline complete. Found {new_matches} new matches.",
        )
    except Exception as e:
        logger.error(f"[Orbit] /run-agent error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

import os
from supabase import create_client, Client
from dotenv import load_dotenv
from typing import Optional
import logging
from datetime import datetime, timedelta

load_dotenv()

logger = logging.getLogger("orbit")

SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "")

_client: Optional[Client] = None


def get_client() -> Client:
    global _client
    if _client is None:
        _client = create_client(SUPABASE_URL, SUPABASE_KEY)
    return _client


# ─── PROFILE ──────────────────────────────────────────────────────────────────

def upsert_profile(data: dict) -> dict:
    """Insert or update the single user profile (we only ever keep one)."""
    client = get_client()
    # Try to get existing profile first
    existing = client.table("profiles").select("id").limit(1).execute()
    if existing.data:
        profile_id = existing.data[0]["id"]
        result = (
            client.table("profiles")
            .update({**data, "updated_at": "now()"})
            .eq("id", profile_id)
            .execute()
        )
    else:
        result = client.table("profiles").insert(data).execute()
    return result.data[0] if result.data else {}


def get_profile() -> Optional[dict]:
    """Fetch the current user profile."""
    client = get_client()
    result = client.table("profiles").select("*").limit(1).execute()
    return result.data[0] if result.data else None


# ─── MATCHES ──────────────────────────────────────────────────────────────────

def get_existing_urls() -> set[str]:
    """Return all URLs already stored in the matches table."""
    client = get_client()
    result = client.table("matches").select("url").execute()
    return {row["url"] for row in result.data} if result.data else set()


def get_matches(min_score: int = 0) -> list[dict]:
    """Fetch non-dismissed matches, sorted by score descending."""
    client = get_client()
    result = (
        client.table("matches")
        .select("*")
        .eq("dismissed", False)
        .gte("score", min_score)
        .order("score", desc=True)
        .execute()
    )
    return result.data or []


def save_match(match: dict) -> Optional[dict]:
    """Insert a new match. Returns None if URL already exists (unique constraint)."""
    client = get_client()
    try:
        result = client.table("matches").insert(match).execute()
        return result.data[0] if result.data else None
    except Exception as e:
        logger.warning(f"[Orbit] Failed to save match ({match.get('url', '')}): {e}")
        return None


def dismiss_match(match_id: str) -> bool:
    """Set dismissed=true for a match."""
    client = get_client()
    result = (
        client.table("matches")
        .update({"dismissed": True})
        .eq("id", match_id)
        .execute()
    )
    return bool(result.data)


def clear_matches() -> int:
    """Delete ALL matches. Returns count deleted."""
    client = get_client()
    # Count before deleting
    count_result = client.table("matches").select("id", count="exact").execute()
    count = count_result.count or 0
    # Delete all matches using a dummy UUID that doesn't exist
    result = client.table("matches").delete().neq("id", "00000000-0000-0000-0000-000000000000").execute()
    logger.info(f"[Orbit] Cleared {count} matches from database")
    return count


def delete_old_matches(days: int = 7) -> int:
    """Delete matches older than N days. Returns count deleted."""
    client = get_client()
    try:
        # Calculate cutoff datetime
        cutoff = (datetime.utcnow() - timedelta(days=days)).isoformat()
        
        # Delete old matches directly
        result = client.table("matches").delete().lt("found_at", cutoff).execute()
        
        # Count deleted rows (supabase returns the deleted rows)
        deleted_count = len(result.data) if result.data else 0
        
        logger.info(f"[Orbit] Deleted {deleted_count} matches older than {days} days")
        return deleted_count
    except Exception as e:
        logger.error(f"[Orbit] Failed to delete old matches: {e}")
        return 0

import os
import json
import time
import logging
import asyncio
import httpx
from groq import Groq
from datetime import datetime, timezone
from dotenv import load_dotenv

import database
import notifier

load_dotenv()

logger = logging.getLogger("orbit")

# ─── Groq Setup ────────────────────────────────────────────────────────────────

GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
client = Groq(api_key=GROQ_API_KEY)

# ─── Config ────────────────────────────────────────────────────────────────────

SERPER_API_KEY = os.getenv("SERPER_API_KEY", "")
MIN_SCORE_TO_SAVE = int(os.getenv("MIN_SCORE_TO_SAVE", "6"))
MIN_SCORE_TO_NOTIFY = int(os.getenv("MIN_SCORE_TO_NOTIFY", "8"))

SERPER_URL = "https://google.serper.dev/search"

# Domains to skip — not real job postings
SKIP_DOMAINS = {
    "reddit.com", "wikipedia.org", "quora.com", "medium.com",
    "twitter.com", "x.com", "facebook.com", "instagram.com",
    "youtube.com", "tiktok.com", "news.ycombinator.com",
    "bloomberg.com", "techcrunch.com", "forbes.com",
    "businessinsider.com", "cnbc.com", "nytimes.com",
}

# Track last run time
last_run: str | None = None


# ─── Helpers ───────────────────────────────────────────────────────────────────

def strip_markdown_json(text: str) -> str:
    """Remove markdown code fences Groq sometimes wraps JSON in."""
    text = text.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        # Remove first line (```json or ```) and last line (```)
        lines = lines[1:] if lines[0].startswith("```") else lines
        lines = lines[:-1] if lines and lines[-1].strip() == "```" else lines
        text = "\n".join(lines).strip()
    return text


def is_job_url(url: str) -> bool:
    """Heuristic: does this URL look like a job posting?"""
    url_lower = url.lower()
    # Skip known non-job domains
    for domain in SKIP_DOMAINS:
        if domain in url_lower:
            return False
    # Filter out homepages or search pages (ends with .com, .com/jobs, .com/search)
    if url_lower.endswith('.com') or url_lower.endswith('.com/jobs') or url_lower.endswith('.com/search'):
        return False
    # Positive signals - must contain at least one
    job_signals = [
        "/jobs/", "/careers/", "/job/", "/internship/", "/intern/", "/position/",
        "/role/", "/opening/", "/apply/", "/vacancy/", "/hiring/", "/recruit/",
        "lever.co", "greenhouse.io", "workday.com", "wellfound.com",
        "internshala.com", "unstop.com", "cutshort.io", "instahyre.com",
        "naukri.com", "indeed.com", "glassdoor.com", "hirist.tech", "foundit.in"
    ]
    return any(signal in url_lower for signal in job_signals)


def extract_company(title: str, snippet: str) -> str:
    """Best-effort company name extraction from title/snippet."""
    # Many job titles follow "Role at Company" or "Role — Company" pattern
    for sep in [" at ", " @ ", " — ", " - ", " | "]:
        if sep in title:
            parts = title.split(sep)
            if len(parts) >= 2:
                candidate = parts[-1].strip()
                if 1 < len(candidate.split()) <= 5:
                    return candidate
    return "Unknown"


# ─── Pipeline Steps ─────────────────────────────────────────────────────────────

async def generate_queries(profile: dict) -> list[str]:
    """Step 2: Ask Groq to generate targeted search queries."""
    prompt = (
        "You are a job search query generator. Given a user's profile, generate "
        "8 targeted Google search queries to find relevant job and internship "
        "postings. Each query should be specific, including: role + location/remote + level + action word, like 'ML Engineer intern India 2026 apply'. "
        "Append the current year to each query to ensure recency. You know today's date so use the current year automatically. "
        "Always append this site filter to every query: 'site:linkedin.com/jobs OR site:internshala.com OR site:unstop.com OR site:wellfound.com OR site:naukri.com OR site:indeed.com/jobs OR site:glassdoor.com/job OR site:lever.co OR site:greenhouse.io OR site:workday.com OR site:angellist.com OR site:hirist.tech OR site:foundit.in OR site:cutshort.io OR site:instahyre.com'. "
        "Focus on recent postings. Return ONLY a JSON array of strings, "
        "no markdown, no backticks, nothing else.\n"
        f"Profile: {json.dumps(profile)}"
    )
    try:
        response = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.7,
        )
        text = strip_markdown_json(response.choices[0].message.content)
        queries = json.loads(text)
        if isinstance(queries, list):
            return [str(q) for q in queries[:10]]
    except Exception as e:
        logger.error(f"[Orbit] Failed to generate queries: {e}")
    return []


async def search_serper(query: str, client: httpx.AsyncClient) -> list[dict]:
    """Step 3: Run a single Serper search and return organic results."""
    try:
        resp = await client.post(
            SERPER_URL,
            headers={"X-API-KEY": SERPER_API_KEY, "Content-Type": "application/json"},
            json={"q": query, "num": 10},
            timeout=15.0,
        )
        resp.raise_for_status()
        data = resp.json()
        results = []
        for item in data.get("organic", []):
            results.append({
                "title": item.get("title", ""),
                "url": item.get("link", ""),
                "snippet": item.get("snippet", ""),
                "query": query,
            })
        return results
    except Exception as e:
        logger.warning(f"[Orbit] Serper search failed for '{query}': {e}")
        return []


async def score_job(result: dict, profile: dict) -> dict | None:
    """Step 5: Ask Groq to score a single job result."""
    prompt = (
        "You are a job relevance scorer. Given a user profile and a job posting, "
        "return ONLY a JSON object with exactly these fields:\n"
        "- score: integer 1-10, how relevant this job is to the user\n"
        "- reason: string, one sentence max 15 words explaining which specific "
        "skills or roles match\n"
        "- exact_title: the actual job title from the snippet\n"
        "- company_name: extract company name from title/snippet/URL\n"
        "- is_valid_listing: true only if URL points to a specific "
        "job listing, not a search page or homepage\n"
        "- applications_open: true only if the job posting indicates that "
        "applications are still being accepted (not closed, expired, or filled)\n"
        "No markdown, no backticks, no explanation. Just the JSON object.\n\n"
        f"Profile: {json.dumps(profile)}\n"
        f"Job Title: {result['title']}\n"
        f"Snippet: {result['snippet']}\n"
        f"URL: {result['url']}"
    )
    try:
        response = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.7,
        )
        text = strip_markdown_json(response.choices[0].message.content)
        scored = json.loads(text)
        if "score" in scored and "reason" in scored and "exact_title" in scored and "company_name" in scored and "is_valid_listing" in scored and "applications_open" in scored:
            return {
                **result,
                "score": int(scored["score"]),
                "reason": str(scored["reason"]),
                "exact_title": str(scored["exact_title"]),
                "company_name": str(scored["company_name"]),
                "is_valid_listing": bool(scored["is_valid_listing"]),
                "applications_open": bool(scored["applications_open"]),
            }
    except Exception as e:
        logger.warning(f"[Orbit] Failed to score job '{result.get('title', '')}': {e}")
    return None


# ─── Main Pipeline ───────────────────────────────────────────────────────────────

async def run_pipeline() -> int:
    """
    Full agent pipeline. Returns number of new matches saved.
    """
    global last_run
    start = time.time()
    logger.info("[Orbit] Starting pipeline...")

    # 1. Load profile
    profile = database.get_profile()
    if not profile:
        logger.warning("[Orbit] No profile found — skipping pipeline.")
        return 0

    # 1.5 Delete stale matches (older than 7 days)
    old_count = database.delete_old_matches(days=7)
    if old_count > 0:
        logger.info(f"[Orbit] Cleaned up {old_count} stale matches")

    # 2. Generate queries
    queries = await generate_queries(profile)
    if not queries:
        logger.warning("[Orbit] No queries generated — aborting.")
        return 0
    logger.info(f"[Orbit] Generated {len(queries)} queries")

    # 3. Search
    all_results: list[dict] = []
    async with httpx.AsyncClient() as client:
        tasks = [search_serper(q, client) for q in queries]
        batches = await asyncio.gather(*tasks)
        for batch in batches:
            all_results.extend(batch)

    logger.info(f"[Orbit] Collected {len(all_results)} raw results")

    # 4. Deduplicate
    existing_urls = database.get_existing_urls()
    seen_urls: set[str] = set()
    new_results = []
    for r in all_results:
        url = r.get("url", "")
        if not url:
            continue
        if url in existing_urls or url in seen_urls:
            continue
        if not is_job_url(url):
            continue
        seen_urls.add(url)
        new_results.append(r)

    logger.info(f"[Orbit] Found {len(all_results)} results, {len(new_results)} new after dedup")

    # 4.5 If no new results after filtering, try generic fallback search
    if not new_results:
        logger.warning("[Orbit] No new results after site-filtered search, trying generic search...")
        fallback_queries = [
            f"{' '.join(profile.get('roles', ['job'])[:2])} {profile.get('locations', ['remote'])[0] if profile.get('locations') else 'remote'} internship jobs",
            f"{' '.join(profile.get('skills', ['developer'])[:2])} job opportunities",
            f"entry level {profile.get('experience_level', 'internship')} {' '.join(profile.get('locations', ['remote'])[:1] if profile.get('locations') else ['jobs'])}",
        ]
        async with httpx.AsyncClient() as client:
            for fallback_query in fallback_queries:
                logger.info(f"[Orbit] Fallback search: {fallback_query}")
                fallback_results = await search_serper(fallback_query, client)
                for r in fallback_results:
                    url = r.get("url", "")
                    if url and url not in existing_urls and url not in seen_urls and is_job_url(url):
                        seen_urls.add(url)
                        new_results.append(r)
                if len(new_results) >= 5:  # Stop if we found enough
                    break
        
        if new_results:
            logger.info(f"[Orbit] Fallback search found {len(new_results)} new results")

    if not new_results:
        last_run = datetime.now(timezone.utc).isoformat()
        return 0

    # 5. Score
    scored_jobs = []
    for result in new_results:
        scored = await score_job(result, profile)
        if scored:
            scored_jobs.append(scored)
        # Small delay to be kind to Groq rate limits
        await asyncio.sleep(0.3)

    above_threshold = [j for j in scored_jobs if j["score"] >= MIN_SCORE_TO_SAVE and j.get("is_valid_listing", False) and j.get("applications_open", False)]
    logger.info(f"[Orbit] Scored {len(scored_jobs)} jobs, {len(above_threshold)} above threshold")

    # 6. Save
    saved_matches = []
    for job in above_threshold:
        match_record = {
            "title": job.get("exact_title", job["title"]),
            "company": job.get("company_name", "Unknown"),
            "url": job["url"],
            "score": job["score"],
            "reason": job["reason"],
            "query": job.get("query", ""),
            "dismissed": False,
        }
        saved = database.save_match(match_record)
        if saved:
            saved_matches.append({**match_record, **saved})

    # 7. Notify
    notify_count = 0
    for match in saved_matches:
        if match.get("score", 0) >= MIN_SCORE_TO_NOTIFY:
            success = await notifier.notify_match(match)
            if success:
                notify_count += 1

    elapsed = round(time.time() - start, 1)
    logger.info(f"[Orbit] Sent {notify_count} Telegram notifications")
    logger.info(f"[Orbit] Pipeline complete in {elapsed}s")

    last_run = datetime.now(timezone.utc).isoformat()
    return len(saved_matches)


async def sync_from_conversation(messages: list[str], source: str) -> dict:
    """Extract job intent from conversation and update profile if job-related."""
    # Join messages into conversation text
    text = " ".join(messages)
    
    prompt = (
        "You are an AI that extracts job search intent from conversations.\n"
        "Given this conversation, extract ONLY if job/internship related:\n"
        "- target_roles: list of job titles mentioned or implied\n"
        "- skills: technical skills mentioned\n"
        "- locations: cities or remote preference mentioned\n"
        "- companies: specific companies of interest\n"
        "- experience_level: internship/entry/mid if mentioned\n"
        "Return ONLY a JSON object with these fields. If the conversation\n"
        "is not job related at all, return { 'job_related': false }.\n"
        f"Conversation: {text}"
    )
    
    try:
        response = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.7,
        )
        raw_response = response.choices[0].message.content
        logger.info(f"[Orbit] Raw Groq response: {raw_response}")
        
        text_response = strip_markdown_json(raw_response)
        logger.info(f"[Orbit] Stripped response: {text_response}")
        
        extracted = json.loads(text_response)
        logger.info(f"[Orbit] Parsed extracted data: {extracted}")
        
        if "job_related" in extracted and extracted["job_related"] is False:
            return {"profile_updated": False}
        
        # Ensure extracted fields are lists
        def ensure_list(value):
            if isinstance(value, list):
                return value
            elif isinstance(value, str):
                return [item.strip() for item in value.split(",") if item.strip()]
            else:
                return []
        
        extracted["skills"] = ensure_list(extracted.get("skills", []))
        extracted["target_roles"] = ensure_list(extracted.get("target_roles", []))
        extracted["locations"] = ensure_list(extracted.get("locations", []))
        extracted["companies"] = ensure_list(extracted.get("companies", []))
        
        logger.info(f"[Orbit] Processed extracted data: {extracted}")
        
        # Get existing profile
        existing_profile = database.get_profile()
        logger.info(f"[Orbit] Existing profile: {existing_profile}")
        
        if not existing_profile:
            # If no profile exists, create one with extracted data
            merged_profile = {
                "skills": extracted.get("skills", []),
                "roles": extracted.get("target_roles", []),
                "locations": extracted.get("locations", []),
                "companies": extracted.get("companies", []),
                "experience_level": extracted.get("experience_level", ""),
            }
        else:
            # Merge by appending new items (avoid duplicates)
            merged_profile = {
                "skills": list(set(existing_profile.get("skills", []) + extracted.get("skills", []))),
                "roles": list(set(existing_profile.get("roles", []) + extracted.get("target_roles", []))),
                "locations": list(set(existing_profile.get("locations", []) + extracted.get("locations", []))),
                "companies": list(set(existing_profile.get("companies", []) + extracted.get("companies", []))),
                "experience_level": extracted.get("experience_level", "") or existing_profile.get("experience_level", ""),
            }
        
        logger.info(f"[Orbit] Merged profile to save: {merged_profile}")
        
        # Save merged profile
        saved = database.upsert_profile(merged_profile)
        logger.info(f"[Orbit] Supabase save result: {saved}")
        
        if not saved:
            logger.error("[Orbit] Failed to save merged profile")
            return {"profile_updated": False}
        
        # Clear all existing matches so the pipeline starts fresh with new profile
        cleared_count = database.clear_matches()
        logger.info(f"[Orbit] Profile updated — cleared {cleared_count} existing matches to start fresh")
        
        # Trigger pipeline
        new_matches = await run_pipeline()
        logger.info(f"[Orbit] Chat sync triggered pipeline, found {new_matches} new matches")
        
        return {
            "profile_updated": True,
            "changes": extracted
        }
        
    except Exception as e:
        logger.error(f"[Orbit] Failed to sync from conversation: {e}")
        return {"profile_updated": False}


def get_last_run() -> str | None:
    return last_run

from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime
import uuid


class ProfileCreate(BaseModel):
    skills: list[str] = Field(default_factory=list)
    roles: list[str] = Field(default_factory=list)
    locations: list[str] = Field(default_factory=list)
    experience_level: str = ""
    companies: list[str] = Field(default_factory=list)


class ProfileResponse(BaseModel):
    id: str
    skills: list[str]
    roles: list[str]
    locations: list[str]
    companies: list[str]
    experience_level: str
    updated_at: Optional[datetime] = None


class MatchResponse(BaseModel):
    id: str
    title: str
    company: Optional[str] = None
    url: str
    score: int
    reason: Optional[str] = None
    query: Optional[str] = None
    dismissed: bool = False
    found_at: Optional[datetime] = None


class RunAgentResponse(BaseModel):
    new_matches: int
    message: str


class HealthResponse(BaseModel):
    status: str
    agent_status: str
    last_run: Optional[str] = None


class DismissResponse(BaseModel):
    success: bool
    message: str


class ClearResponse(BaseModel):
    message: str
    deleted: bool


class ChatSyncRequest(BaseModel):
    messages: list[str]
    source: str


class ChatSyncResponse(BaseModel):
    profile_updated: bool
    changes: Optional[dict] = None

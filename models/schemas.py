from pydantic import BaseModel, EmailStr, Field
from typing import Optional, List, Dict, Any
from datetime import datetime

# =======================
# Authentication Schemas
# =======================
class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8)
    full_name: str
    org_name: str
    org_subdomain: str = Field(pattern="^[a-z0-9-]+$")

class LoginRequest(BaseModel):
    email: EmailStr
    password: str

class RefreshRequest(BaseModel):
    refresh_token: str

class TokenResponse(BaseModel):
    access_token: str
    refresh_token: Optional[str] = None
    token_type: str = "bearer"
    user: Optional[Dict[str, Any]] = None
    org: Optional[Dict[str, Any]] = None

# =======================
# Organization Schemas
# =======================
class OrgResponse(BaseModel):
    id: str
    name: str
    subdomain: str
    settings: Dict[str, Any] = {}
    created_at: datetime

class OrgUpdateRequest(BaseModel):
    name: Optional[str] = None
    settings: Optional[Dict[str, Any]] = None

# =======================
# Provider Schemas
# =======================
class ProviderCreate(BaseModel):
    name: str
    provider_type: str
    api_key: str
    config: Dict[str, Any] = {}

class ProviderUpdate(BaseModel):
    name: Optional[str] = None
    config: Optional[Dict[str, Any]] = None
    is_active: Optional[bool] = None

class ProviderResponse(BaseModel):
    id: str
    org_id: Optional[str] = None
    name: str
    provider_type: str
    config: Dict[str, Any] = {}
    is_active: bool
    created_at: Optional[datetime] = None

# =======================
# Assistant Schemas
# =======================
class AssistantCreate(BaseModel):
    name: str
    system_prompt: str
    voice_id: str
    voice_provider: str
    llm_model: str
    llm_provider: str
    stt_provider: str
    tts_provider: str
    first_message: Optional[str] = None
    config: Dict[str, Any] = {}

class AssistantUpdate(BaseModel):
    name: Optional[str] = None
    system_prompt: Optional[str] = None
    voice_id: Optional[str] = None
    voice_provider: Optional[str] = None
    llm_model: Optional[str] = None
    llm_provider: Optional[str] = None
    stt_provider: Optional[str] = None
    tts_provider: Optional[str] = None
    first_message: Optional[str] = None
    config: Optional[Dict[str, Any]] = None
    is_active: Optional[bool] = None

class AssistantResponse(BaseModel):
    id: str
    org_id: Optional[str] = None
    name: str
    system_prompt: str
    voice_id: str
    voice_provider: str
    llm_model: str
    llm_provider: str
    stt_provider: str
    tts_provider: str
    first_message: Optional[str] = None
    config: Dict[str, Any] = {}
    is_active: bool
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

# =======================
# Knowledge Base Schemas
# =======================
class KBDocumentResponse(BaseModel):
    id: str
    org_id: Optional[str] = None
    title: str
    content: Optional[str] = None
    file_url: Optional[str] = None
    file_type: Optional[str] = None
    status: str
    created_at: datetime

class KBSearchRequest(BaseModel):
    query: str
    top_k: int = 3

class KBSearchResponse(BaseModel):
    id: str
    title: str
    content: str
    relevance_score: float

# =======================
# Call Schemas
# =======================
class OutboundCallRequest(BaseModel):
    assistant_id: str
    to_number: str
    from_number: str

class CallResponse(BaseModel):
    id: str
    assistant_id: str
    room_name: str
    direction: str
    from_number: str
    to_number: str
    status: str
    duration_seconds: Optional[int] = None
    recording_url: Optional[str] = None
    started_at: Optional[datetime] = None
    ended_at: Optional[datetime] = None

class TranscriptResponse(BaseModel):
    id: str
    speaker: str
    text: str
    timestamp: datetime

# =======================
# SIP Trunk Schemas
# =======================
class OutboundTrunkCreate(BaseModel):
    name: str
    sip_uri: str
    username: str
    password: str

class OutboundTrunkResponse(BaseModel):
    id: str
    name: str
    sip_uri: str
    livekit_sip_trunk_id: Optional[str] = None
    is_active: bool

class InboundTrunkCreate(BaseModel):
    phone_number: str
    friendly_name: str
    assistant_id: str

class InboundTrunkResponse(BaseModel):
    id: str
    phone_number: str
    friendly_name: str
    assistant_id: str
    livekit_sip_trunk_id: Optional[str] = None

# =======================
# Tool Schemas
# =======================
class ToolCreate(BaseModel):
    name: str
    tool_type: str
    config: Dict[str, Any] = {}
    execution_order: int = 1

class ToolUpdate(BaseModel):
    name: Optional[str] = None
    tool_type: Optional[str] = None
    config: Optional[Dict[str, Any]] = None
    execution_order: Optional[int] = None
    is_active: Optional[bool] = None

class ToolResponse(BaseModel):
    id: str
    name: str
    tool_type: str
    config: Dict[str, Any] = {}
    execution_order: int
    is_active: bool

# =======================
# Callback Schemas
# =======================
class CallbackCreate(BaseModel):
    assistant_id: str
    contact_name: str
    phone_number: str
    scheduled_for: datetime
    reason: Optional[str] = None

class CallbackUpdate(BaseModel):
    status: str

class CallbackResponse(BaseModel):
    id: str
    assistant_id: str
    contact_name: str
    phone_number: str
    scheduled_for: datetime
    reason: Optional[str] = None
    status: str

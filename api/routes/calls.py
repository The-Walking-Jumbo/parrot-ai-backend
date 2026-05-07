import uuid
import re
from datetime import datetime, timezone
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status, Query
from livekit import api

from core.database import db_client, get_db
from api.deps import get_current_user
from core.config import settings
from models.schemas import CallResponse, OutboundCallRequest, TranscriptResponse

router = APIRouter()

def verify_org_access(current_user: dict, org_id: str):
    if current_user.get("org_id") != org_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to access this organization"
        )

# Ensure E.164 format
PHONE_REGEX = re.compile(r"^\+[1-9]\d{1,14}$")

@router.get("", response_model=dict)
async def list_calls(
    org_id: str,
    status: Optional[str] = None,
    assistant_id: Optional[str] = None,
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    current_user: dict = Depends(get_current_user),
    db=Depends(get_db)
):
    verify_org_access(current_user, org_id)
    
    query = "SELECT id, assistant_id, room_name, direction, from_number, to_number, status, duration_seconds, recording_url, started_at, ended_at FROM calls WHERE org_id = ?"
    params = [org_id]
    
    count_query = "SELECT COUNT(*) as total FROM calls WHERE org_id = ?"
    count_params = [org_id]
    
    if status:
        query += " AND status = ?"
        count_query += " AND status = ?"
        params.append(status)
        count_params.append(status)
        
    if assistant_id:
        query += " AND assistant_id = ?"
        count_query += " AND assistant_id = ?"
        params.append(assistant_id)
        count_params.append(assistant_id)
        
    query += " ORDER BY started_at DESC LIMIT ? OFFSET ?"
    params.extend([limit, offset])
    
    total_row = await db_client.fetch_one(count_query, count_params)
    total = total_row["total"] if total_row else 0
    
    rows = await db_client.fetch_all(query, params)
    
    # Parse timestamps for response
    for row in rows:
        if row.get("started_at") and isinstance(row["started_at"], str):
            try:
                row["started_at"] = datetime.fromisoformat(row["started_at"])
            except ValueError:
                pass
        if row.get("ended_at") and isinstance(row["ended_at"], str):
            try:
                row["ended_at"] = datetime.fromisoformat(row["ended_at"])
            except ValueError:
                pass

    return {
        "calls": rows,
        "total": total,
        "limit": limit,
        "offset": offset
    }

@router.post("/outbound", response_model=dict)
async def create_outbound_call(
    org_id: str,
    request: OutboundCallRequest,
    current_user: dict = Depends(get_current_user),
    db=Depends(get_db)
):
    verify_org_access(current_user, org_id)
    
    # 1. Validate assistant exists and is active
    assistant = await db_client.fetch_one(
        "SELECT id, is_active FROM assistants WHERE id = ? AND org_id = ?",
        [request.assistant_id, org_id]
    )
    if not assistant or not bool(assistant.get("is_active")):
        raise HTTPException(status_code=400, detail="Assistant not found or inactive")
        
    # 2. Validate phone numbers (E.164)
    if not PHONE_REGEX.match(request.to_number):
        raise HTTPException(status_code=400, detail="to_number must be in E.164 format (e.g., +1234567890)")
    if not PHONE_REGEX.match(request.from_number):
        raise HTTPException(status_code=400, detail="from_number must be in E.164 format (e.g., +1234567890)")
        
    # 3. Check if outbound trunk is configured
    trunk = await db_client.fetch_one(
        "SELECT livekit_sip_trunk_id FROM sip_trunks WHERE org_id = ? AND direction = 'outbound' AND is_active = 1 LIMIT 1",
        [org_id]
    )
    if not trunk or not trunk.get("livekit_sip_trunk_id"):
        raise HTTPException(status_code=400, detail="No active outbound SIP trunk configured for this organization")
        
    lk_trunk_id = trunk["livekit_sip_trunk_id"]
    
    # 4. & 5. Create LiveKit room and initiate SIP call
    call_id = str(uuid.uuid4())
    room_name = f"call_{call_id}"
    
    lk_http_url = settings.LIVEKIT_URL.replace("ws://", "http://").replace("wss://", "https://")
    
    lk_api = api.LiveKitAPI(
        lk_http_url,
        settings.LIVEKIT_API_KEY,
        settings.LIVEKIT_API_SECRET,
    )
    
    try:
        # Create room
        await lk_api.room.create_room(
            api.CreateRoomRequest(name=room_name)
        )
        
        # Initiate SIP call
        await lk_api.sip.create_sip_participant(
            api.CreateSIPParticipantRequest(
                sip_trunk_id=lk_trunk_id,
                sip_call_to=request.to_number,
                room_name=room_name,
                participant_identity=request.to_number,
            )
        )
    except Exception as e:
        await lk_api.aclose()
        raise HTTPException(status_code=500, detail=f"LiveKit SIP call failed: {str(e)}")
        
    await lk_api.aclose()
    
    # 6. Insert call record
    now = datetime.now(timezone.utc).isoformat()
    await db_client.execute(
        """INSERT INTO calls 
           (id, org_id, assistant_id, room_name, direction, from_number, to_number, status, started_at) 
           VALUES (?, ?, ?, ?, 'outbound', ?, ?, 'initiated', ?)""",
        [call_id, org_id, request.assistant_id, room_name, request.from_number, request.to_number, now]
    )
    
    # 7. Return call_id and room_name
    return {
        "call_id": call_id,
        "room_name": room_name,
        "status": "initiated"
    }

@router.get("/{call_id}", response_model=CallResponse)
async def get_call(
    org_id: str,
    call_id: str,
    current_user: dict = Depends(get_current_user),
    db=Depends(get_db)
):
    verify_org_access(current_user, org_id)
    
    call = await db_client.fetch_one(
        "SELECT id, assistant_id, room_name, direction, from_number, to_number, status, duration_seconds, recording_url, started_at, ended_at FROM calls WHERE id = ? AND org_id = ?",
        [call_id, org_id]
    )
    if not call:
        raise HTTPException(status_code=404, detail="Call not found")
        
    if call.get("started_at") and isinstance(call["started_at"], str):
        try:
            call["started_at"] = datetime.fromisoformat(call["started_at"])
        except ValueError:
            pass
    if call.get("ended_at") and isinstance(call["ended_at"], str):
        try:
            call["ended_at"] = datetime.fromisoformat(call["ended_at"])
        except ValueError:
            pass
            
    return call

@router.get("/{call_id}/transcript", response_model=List[TranscriptResponse])
async def get_call_transcript(
    org_id: str,
    call_id: str,
    current_user: dict = Depends(get_current_user),
    db=Depends(get_db)
):
    verify_org_access(current_user, org_id)
    
    # Verify call belongs to org
    call = await db_client.fetch_one("SELECT id FROM calls WHERE id = ? AND org_id = ?", [call_id, org_id])
    if not call:
        raise HTTPException(status_code=404, detail="Call not found")
        
    rows = await db_client.fetch_all(
        "SELECT id, speaker, text, timestamp FROM transcripts WHERE call_id = ? ORDER BY timestamp ASC",
        [call_id]
    )
    
    for row in rows:
        if row.get("timestamp") and isinstance(row["timestamp"], str):
            try:
                row["timestamp"] = datetime.fromisoformat(row["timestamp"])
            except ValueError:
                pass
                
    return rows

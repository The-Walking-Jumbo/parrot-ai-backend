import json
import logging
import hashlib
import base64
from datetime import datetime, timezone
from fastapi import APIRouter, Request, HTTPException, status
from jose import jwt, JWTError

from core.database import db_client
from core.config import settings

logger = logging.getLogger(__name__)
router = APIRouter()

def verify_livekit_webhook(body: bytes, auth_header: str) -> bool:
    if not auth_header:
        return False
        
    try:
        # The auth_header is typically "Bearer <token>"
        token = auth_header.replace("Bearer ", "")
        
        # Decode the token using our secret
        payload = jwt.decode(token, settings.LIVEKIT_API_SECRET, algorithms=["HS256"])
        
        # Verify the hash in the token matches the body hash
        sha256 = hashlib.sha256()
        sha256.update(body)
        body_hash = base64.b64encode(sha256.digest()).decode('utf-8')
        
        if payload.get("sha256") != body_hash:
            logger.warning("Webhook hash mismatch")
            return False
            
        return True
    except JWTError as e:
        logger.warning(f"Webhook verification failed: {e}")
        return False

@router.post("/livekit")
async def livekit_webhook(request: Request):
    body = await request.body()
    auth_header = request.headers.get("Authorization")
    
    # 1. Verify signature
    # While optional, it's highly recommended to prevent spoofing
    if auth_header and settings.LIVEKIT_API_SECRET:
        if not verify_livekit_webhook(body, auth_header):
            logger.warning("Invalid LiveKit webhook signature")
            raise HTTPException(status_code=401, detail="Invalid signature")

    try:
        data = json.loads(body)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON")
        
    event_type = data.get("event")
    room_data = data.get("room", {})
    room_name = room_data.get("name")
    
    if not room_name:
        return {"status": "ignored", "reason": "No room name"}
        
    # Find call by room_name
    result = await db_client.execute(
        "SELECT id, status, started_at FROM calls WHERE room_name = ?",
        [room_name]
    )
    
    if not result.rows:
        return {"status": "ignored", "reason": "Unknown room"}
        
    call_id = result.rows[0][0]
    current_status = result.rows[0][1]
    started_at_str = result.rows[0][2]
    
    now = datetime.now(timezone.utc)
    
    if event_type == "room_started":
        if current_status != 'completed':
            await db_client.execute(
                "UPDATE calls SET status = 'in_progress' WHERE id = ?",
                [call_id]
            )
            
    elif event_type == "room_finished":
        duration = 0
        if started_at_str:
            try:
                # Handle ISO formats correctly for duration calculation
                started_at = datetime.fromisoformat(started_at_str.replace("Z", "+00:00"))
                # Ensure 'now' is tz-aware for the math
                duration = int((now - started_at).total_seconds())
                # Fallback safeguard against negative durations due to clock skew
                duration = max(0, duration) 
            except ValueError:
                logger.warning(f"Failed to parse started_at timestamp: {started_at_str}")
                
        await db_client.execute(
            "UPDATE calls SET status = 'completed', ended_at = ?, duration_seconds = ? WHERE id = ?",
            [now.isoformat(), duration, call_id]
        )
        
        # TODO: Trigger post-call tools (async task)
        # await execute_post_call_tools(call_id)
        
    elif event_type in ["participant_joined", "participant_left", "track_published", "track_unpublished"]:
        # Standardize state progression if we get a join event before room_started (race conditions)
        if event_type == "participant_joined" and current_status == "initiated":
            await db_client.execute(
                "UPDATE calls SET status = 'in_progress' WHERE id = ?",
                [call_id]
            )
            
    return {"status": "processed", "event": event_type}

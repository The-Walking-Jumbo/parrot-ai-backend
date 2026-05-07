import uuid
import json
import logging
from typing import List
from fastapi import APIRouter, Depends, HTTPException, status
from livekit import api

from core.database import db_client, get_db
from api.deps import get_current_user
from core.config import settings
from core.security import encrypt_value
from models.schemas import OutboundTrunkCreate, OutboundTrunkResponse, InboundTrunkCreate, InboundTrunkResponse

logger = logging.getLogger(__name__)
router = APIRouter()

def verify_org_access(current_user: dict, org_id: str, require_admin: bool = False):
    if current_user.get("org_id") != org_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to access this organization"
        )
    if require_admin and current_user.get("role") != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only administrators can manage SIP trunks"
        )

def get_lk_api():
    lk_http_url = settings.LIVEKIT_URL.replace("ws://", "http://").replace("wss://", "https://")
    return api.LiveKitAPI(
        lk_http_url,
        settings.LIVEKIT_API_KEY,
        settings.LIVEKIT_API_SECRET,
    )

# --- Outbound Trunks ---

@router.get("/outbound", response_model=List[OutboundTrunkResponse])
async def list_outbound_trunks(
    org_id: str,
    current_user: dict = Depends(get_current_user),
    db=Depends(get_db)
):
    verify_org_access(current_user, org_id)
    
    rows = await db_client.fetch_all(
        "SELECT id, name, sip_uri, livekit_sip_trunk_id, is_active FROM sip_trunks WHERE org_id = ? AND direction = 'outbound'",
        [org_id]
    )
    for row in rows:
        row["is_active"] = bool(row["is_active"])
    return rows

@router.post("/outbound", response_model=OutboundTrunkResponse)
async def create_outbound_trunk(
    org_id: str,
    request: OutboundTrunkCreate,
    current_user: dict = Depends(get_current_user),
    db=Depends(get_db)
):
    verify_org_access(current_user, org_id, require_admin=True)
    
    trunk_id = str(uuid.uuid4())
    lk_custom_id = f"outbound_{trunk_id}"
    
    lk_api = get_lk_api()
    try:
        sip_trunk = await lk_api.sip.create_sip_outbound_trunk(
            api.CreateSIPOutboundTrunkRequest(
                trunk=api.SIPOutboundTrunkInfo(
                    sip_trunk_id=lk_custom_id,
                    name=request.name,
                    address=request.sip_uri,
                    transport=api.SIPTransport.SIP_TRANSPORT_UDP,
                    numbers=[],
                    auth_username=request.username,
                    auth_password=request.password,
                )
            )
        )
    except Exception as e:
        await lk_api.aclose()
        logger.error(f"LiveKit create_sip_outbound_trunk failed: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to create SIP trunk in LiveKit: {str(e)}")
        
    await lk_api.aclose()
    
    returned_lk_trunk_id = sip_trunk.sip_trunk_id if hasattr(sip_trunk, "sip_trunk_id") else lk_custom_id
    
    encrypted_password = encrypt_value(request.password)
    
    await db_client.execute(
        """INSERT INTO sip_trunks 
           (id, org_id, direction, name, sip_uri, username, password, livekit_sip_trunk_id, is_active) 
           VALUES (?, ?, 'outbound', ?, ?, ?, ?, ?, 1)""",
        [trunk_id, org_id, request.name, request.sip_uri, request.username, encrypted_password, returned_lk_trunk_id]
    )
    
    return OutboundTrunkResponse(
        id=trunk_id,
        name=request.name,
        sip_uri=request.sip_uri,
        livekit_sip_trunk_id=returned_lk_trunk_id,
        is_active=True
    )

@router.delete("/outbound/{trunk_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_outbound_trunk(
    org_id: str,
    trunk_id: str,
    current_user: dict = Depends(get_current_user),
    db=Depends(get_db)
):
    verify_org_access(current_user, org_id, require_admin=True)
    
    trunk = await db_client.fetch_one(
        "SELECT id, livekit_sip_trunk_id FROM sip_trunks WHERE id = ? AND org_id = ? AND direction = 'outbound'",
        [trunk_id, org_id]
    )
    
    if not trunk:
        raise HTTPException(status_code=404, detail="Outbound trunk not found")
        
    if trunk.get("livekit_sip_trunk_id"):
        lk_api = get_lk_api()
        try:
            await lk_api.sip.delete_sip_trunk(
                api.DeleteSIPTrunkRequest(sip_trunk_id=trunk["livekit_sip_trunk_id"])
            )
        except Exception as e:
            logger.warning(f"Failed to delete SIP trunk in LiveKit (might already be deleted): {e}")
        finally:
            await lk_api.aclose()
            
    await db_client.execute("DELETE FROM sip_trunks WHERE id = ?", [trunk_id])
    return None

# --- Inbound Trunks ---

@router.get("/inbound", response_model=List[InboundTrunkResponse])
async def list_inbound_trunks(
    org_id: str,
    current_user: dict = Depends(get_current_user),
    db=Depends(get_db)
):
    verify_org_access(current_user, org_id)
    
    rows = await db_client.fetch_all(
        "SELECT id, phone_number, friendly_name, assistant_id, livekit_sip_trunk_id FROM sip_trunks WHERE org_id = ? AND direction = 'inbound'",
        [org_id]
    )
    return rows

@router.post("/inbound", response_model=InboundTrunkResponse)
async def create_inbound_trunk(
    org_id: str,
    request: InboundTrunkCreate,
    current_user: dict = Depends(get_current_user),
    db=Depends(get_db)
):
    verify_org_access(current_user, org_id, require_admin=True)
    
    # 1. Validate assistant exists
    assistant = await db_client.fetch_one("SELECT id FROM assistants WHERE id = ? AND org_id = ?", [request.assistant_id, org_id])
    if not assistant:
        raise HTTPException(status_code=400, detail="Assistant not found")
        
    # 2. Validate phone number uniqueness across ALL orgs (SIP routing is global)
    existing_number = await db_client.fetch_one("SELECT id FROM sip_trunks WHERE phone_number = ? AND direction = 'inbound'", [request.phone_number])
    if existing_number:
        raise HTTPException(status_code=400, detail="This phone number is already configured")
        
    trunk_id = str(uuid.uuid4())
    lk_custom_id = f"inbound_{trunk_id}"
    
    lk_api = get_lk_api()
    try:
        sip_trunk = await lk_api.sip.create_sip_inbound_trunk(
            api.CreateSIPInboundTrunkRequest(
                trunk=api.SIPInboundTrunkInfo(
                    sip_trunk_id=lk_custom_id,
                    name=request.friendly_name,
                    numbers=[request.phone_number],
                    allowed_addresses=[],  # Allow all for general use, or specific if required
                    metadata=json.dumps({"org_id": org_id, "assistant_id": request.assistant_id}),
                )
            )
        )
    except Exception as e:
        await lk_api.aclose()
        logger.error(f"LiveKit create_sip_inbound_trunk failed: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to create inbound SIP trunk in LiveKit: {str(e)}")
        
    await lk_api.aclose()
    
    returned_lk_trunk_id = sip_trunk.sip_trunk_id if hasattr(sip_trunk, "sip_trunk_id") else lk_custom_id
    
    await db_client.execute(
        """INSERT INTO sip_trunks 
           (id, org_id, direction, phone_number, friendly_name, assistant_id, livekit_sip_trunk_id, is_active) 
           VALUES (?, ?, 'inbound', ?, ?, ?, ?, 1)""",
        [trunk_id, org_id, request.phone_number, request.friendly_name, request.assistant_id, returned_lk_trunk_id]
    )
    
    return InboundTrunkResponse(
        id=trunk_id,
        phone_number=request.phone_number,
        friendly_name=request.friendly_name,
        assistant_id=request.assistant_id,
        livekit_sip_trunk_id=returned_lk_trunk_id
    )

@router.delete("/inbound/{trunk_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_inbound_trunk(
    org_id: str,
    trunk_id: str,
    current_user: dict = Depends(get_current_user),
    db=Depends(get_db)
):
    verify_org_access(current_user, org_id, require_admin=True)
    
    trunk = await db_client.fetch_one(
        "SELECT id, livekit_sip_trunk_id FROM sip_trunks WHERE id = ? AND org_id = ? AND direction = 'inbound'",
        [trunk_id, org_id]
    )
    
    if not trunk:
        raise HTTPException(status_code=404, detail="Inbound trunk not found")
        
    if trunk.get("livekit_sip_trunk_id"):
        lk_api = get_lk_api()
        try:
            await lk_api.sip.delete_sip_trunk(
                api.DeleteSIPTrunkRequest(sip_trunk_id=trunk["livekit_sip_trunk_id"])
            )
        except Exception as e:
            logger.warning(f"Failed to delete SIP trunk in LiveKit (might already be deleted): {e}")
        finally:
            await lk_api.aclose()
            
    await db_client.execute("DELETE FROM sip_trunks WHERE id = ?", [trunk_id])
    return None

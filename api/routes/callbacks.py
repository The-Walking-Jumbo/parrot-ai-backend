import uuid
import re
from datetime import datetime, timezone
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status, Query

from core.database import db_client, get_db
from api.deps import get_current_user
from models.schemas import CallbackCreate, CallbackUpdate, CallbackResponse

router = APIRouter()

PHONE_REGEX = re.compile(r"^\+[1-9]\d{1,14}$")

def verify_org_access(current_user: dict, org_id: str, require_admin: bool = False):
    if current_user.get("org_id") != org_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to access this organization"
        )
    if require_admin and current_user.get("role") != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only administrators can manage callbacks"
        )

@router.get("", response_model=List[CallbackResponse])
async def list_callbacks(
    org_id: str,
    status_filter: Optional[str] = Query(None, alias="status"),
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None,
    current_user: dict = Depends(get_current_user),
    db=Depends(get_db)
):
    verify_org_access(current_user, org_id)
    
    query = "SELECT id, assistant_id, contact_name, phone_number, scheduled_for, reason, status FROM callbacks WHERE org_id = ?"
    params = [org_id]
    
    if status_filter:
        query += " AND status = ?"
        params.append(status_filter)
        
    if start_date:
        query += " AND scheduled_for >= ?"
        params.append(start_date.isoformat())
        
    if end_date:
        query += " AND scheduled_for <= ?"
        params.append(end_date.isoformat())
        
    query += " ORDER BY scheduled_for ASC"
    
    rows = await db_client.fetch_all(query, params)
    
    for row in rows:
        if row.get("scheduled_for") and isinstance(row["scheduled_for"], str):
            try:
                row["scheduled_for"] = datetime.fromisoformat(row["scheduled_for"])
            except ValueError:
                pass
                
    return rows

@router.post("", response_model=CallbackResponse)
async def create_callback(
    org_id: str,
    request: CallbackCreate,
    current_user: dict = Depends(get_current_user),
    db=Depends(get_db)
):
    verify_org_access(current_user, org_id)
    
    # Validate assistant
    assistant = await db_client.fetch_one("SELECT id FROM assistants WHERE id = ? AND org_id = ?", [request.assistant_id, org_id])
    if not assistant:
        raise HTTPException(status_code=400, detail="Assistant not found")
        
    # Validate phone number
    if not PHONE_REGEX.match(request.phone_number):
        raise HTTPException(status_code=400, detail="Phone number must be in E.164 format (e.g., +1234567890)")
        
    # Validate scheduled_for is in the future
    now = datetime.now(timezone.utc)
    # Ensure request.scheduled_for is UTC aware for comparison
    if request.scheduled_for.tzinfo is None:
        scheduled_for = request.scheduled_for.replace(tzinfo=timezone.utc)
    else:
        scheduled_for = request.scheduled_for
        
    if scheduled_for <= now:
        raise HTTPException(status_code=400, detail="Scheduled time must be in the future")
        
    callback_id = str(uuid.uuid4())
    status_val = "pending"
    
    await db_client.execute(
        """INSERT INTO callbacks 
           (id, org_id, assistant_id, contact_name, phone_number, scheduled_for, reason, status) 
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        [callback_id, org_id, request.assistant_id, request.contact_name, request.phone_number, scheduled_for.isoformat(), request.reason, status_val]
    )
    
    return CallbackResponse(
        id=callback_id,
        assistant_id=request.assistant_id,
        contact_name=request.contact_name,
        phone_number=request.phone_number,
        scheduled_for=scheduled_for,
        reason=request.reason,
        status=status_val
    )

@router.patch("/{callback_id}", response_model=CallbackResponse)
async def update_callback(
    org_id: str,
    callback_id: str,
    update_data: CallbackUpdate,
    current_user: dict = Depends(get_current_user),
    db=Depends(get_db)
):
    verify_org_access(current_user, org_id)
    
    callback = await db_client.fetch_one("SELECT * FROM callbacks WHERE id = ? AND org_id = ?", [callback_id, org_id])
    if not callback:
        raise HTTPException(status_code=404, detail="Callback not found")
        
    fields = []
    params = []
    
    if update_data.status is not None:
        fields.append("status = ?")
        params.append(update_data.status)
        callback["status"] = update_data.status
        
        # When status changes to 'completed', we will eventually log the completed_call_id
        # if update_data.status == 'completed':
        #     fields.append("completed_call_id = ?")
        #     params.append(associated_call_id)
            
    if fields:
        query = f"UPDATE callbacks SET {', '.join(fields)} WHERE id = ?"
        params.append(callback_id)
        await db_client.execute(query, params)
        
    if callback.get("scheduled_for") and isinstance(callback["scheduled_for"], str):
        try:
            callback["scheduled_for"] = datetime.fromisoformat(callback["scheduled_for"])
        except ValueError:
            pass
            
    return callback

@router.delete("/{callback_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_callback(
    org_id: str,
    callback_id: str,
    current_user: dict = Depends(get_current_user),
    db=Depends(get_db)
):
    verify_org_access(current_user, org_id)
    await db_client.execute("DELETE FROM callbacks WHERE id = ? AND org_id = ?", [callback_id, org_id])
    return None

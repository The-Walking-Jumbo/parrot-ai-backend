import uuid
import json
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, status
from typing import List

from core.database import db_client, get_db
from api.deps import get_current_user
from models.schemas import AssistantCreate, AssistantUpdate, AssistantResponse

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
            detail="Only administrators can manage assistants"
        )

async def verify_providers_exist(org_id: str, provider_names: list):
    """Verify that all referenced providers exist and are active in the organization."""
    if not provider_names:
        return
        
    placeholders = ", ".join(["?"] * len(provider_names))
    query = f"SELECT name FROM providers WHERE org_id = ? AND is_active = 1 AND name IN ({placeholders})"
    params = [org_id] + provider_names
    
    rows = await db_client.fetch_all(query, params)
    found_providers = {row["name"] for row in rows}
    
    missing = set(provider_names) - found_providers
    if missing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"The following providers do not exist or are inactive: {', '.join(missing)}"
        )

@router.get("", response_model=List[AssistantResponse])
async def get_assistants(
    org_id: str,
    current_user: dict = Depends(get_current_user),
    db=Depends(get_db)
):
    verify_org_access(current_user, org_id)
    
    rows = await db_client.fetch_all(
        """SELECT id, org_id, name, system_prompt, voice_id, voice_provider, 
                  llm_model, llm_provider, stt_provider, tts_provider, first_message, 
                  config, is_active, created_at, updated_at 
           FROM assistants WHERE org_id = ?""",
        [org_id]
    )
    
    for row in rows:
        row["config"] = json.loads(row["config"]) if row.get("config") else {}
        row["is_active"] = bool(row["is_active"])
        
    return rows

@router.get("/{assistant_id}", response_model=AssistantResponse)
async def get_assistant(
    org_id: str,
    assistant_id: str,
    current_user: dict = Depends(get_current_user),
    db=Depends(get_db)
):
    verify_org_access(current_user, org_id)
    
    row = await db_client.fetch_one(
        """SELECT id, org_id, name, system_prompt, voice_id, voice_provider, 
                  llm_model, llm_provider, stt_provider, tts_provider, first_message, 
                  config, is_active, created_at, updated_at 
           FROM assistants WHERE id = ? AND org_id = ?""",
        [assistant_id, org_id]
    )
    
    if not row:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Assistant not found")
        
    row["config"] = json.loads(row["config"]) if row.get("config") else {}
    row["is_active"] = bool(row["is_active"])
        
    return row

@router.post("", response_model=AssistantResponse)
async def create_assistant(
    org_id: str,
    assistant: AssistantCreate,
    current_user: dict = Depends(get_current_user),
    db=Depends(get_db)
):
    verify_org_access(current_user, org_id, require_admin=True)
    
    if not assistant.system_prompt.strip():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="System prompt cannot be empty")
        
    # Verify all referenced providers exist
    providers_to_check = [assistant.voice_provider, assistant.llm_provider, assistant.stt_provider, assistant.tts_provider]
    await verify_providers_exist(org_id, list(set(providers_to_check)))
    
    assistant_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    config_json = json.dumps(assistant.config)
    
    await db_client.execute(
        """INSERT INTO assistants 
           (id, org_id, name, system_prompt, voice_id, voice_provider, llm_model, llm_provider, stt_provider, tts_provider, first_message, config, is_active, created_at, updated_at) 
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        [assistant_id, org_id, assistant.name, assistant.system_prompt, assistant.voice_id, assistant.voice_provider, 
         assistant.llm_model, assistant.llm_provider, assistant.stt_provider, assistant.tts_provider, assistant.first_message, 
         config_json, True, now, now]
    )
    
    return AssistantResponse(
        id=assistant_id,
        org_id=org_id,
        **assistant.model_dump(),
        is_active=True,
        created_at=now,
        updated_at=now
    )

@router.patch("/{assistant_id}", response_model=AssistantResponse)
async def update_assistant(
    org_id: str,
    assistant_id: str,
    update_data: AssistantUpdate,
    current_user: dict = Depends(get_current_user),
    db=Depends(get_db)
):
    verify_org_access(current_user, org_id, require_admin=True)
    
    assistant = await db_client.fetch_one("SELECT * FROM assistants WHERE id = ? AND org_id = ?", [assistant_id, org_id])
    if not assistant:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Assistant not found")
        
    if update_data.system_prompt is not None and not update_data.system_prompt.strip():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="System prompt cannot be empty")
        
    # Verify new providers if they are being updated
    providers_to_check = []
    if update_data.voice_provider: providers_to_check.append(update_data.voice_provider)
    if update_data.llm_provider: providers_to_check.append(update_data.llm_provider)
    if update_data.stt_provider: providers_to_check.append(update_data.stt_provider)
    if update_data.tts_provider: providers_to_check.append(update_data.tts_provider)
    
    if providers_to_check:
        await verify_providers_exist(org_id, list(set(providers_to_check)))
        
    fields_to_update = []
    params = []
    
    update_dict = update_data.model_dump(exclude_unset=True)
    
    if "config" in update_dict:
        current_config = json.loads(assistant["config"]) if assistant.get("config") else {}
        current_config.update(update_dict["config"])
        update_dict["config"] = json.dumps(current_config)
        assistant["config"] = current_config
    else:
        assistant["config"] = json.loads(assistant["config"]) if assistant.get("config") else {}
        
    for key, value in update_dict.items():
        if key == "config" and isinstance(value, str):
            fields_to_update.append(f"{key} = ?")
            params.append(value)
        elif key != "config":
            fields_to_update.append(f"{key} = ?")
            params.append(value)
            assistant[key] = value
            
    if fields_to_update:
        now = datetime.now(timezone.utc).isoformat()
        fields_to_update.append("updated_at = ?")
        params.append(now)
        assistant["updated_at"] = now
        
        query = f"UPDATE assistants SET {', '.join(fields_to_update)} WHERE id = ?"
        params.append(assistant_id)
        await db_client.execute(query, params)
        
    assistant["is_active"] = bool(assistant["is_active"])
    
    return assistant

@router.delete("/{assistant_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_assistant(
    org_id: str,
    assistant_id: str,
    current_user: dict = Depends(get_current_user),
    db=Depends(get_db)
):
    verify_org_access(current_user, org_id, require_admin=True)
    
    assistant = await db_client.fetch_one("SELECT id FROM assistants WHERE id = ? AND org_id = ?", [assistant_id, org_id])
    if not assistant:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Assistant not found")
        
    # Soft delete: Preserve call history but mark inactive
    now = datetime.now(timezone.utc).isoformat()
    await db_client.execute(
        "UPDATE assistants SET is_active = 0, updated_at = ? WHERE id = ?",
        [now, assistant_id]
    )
    return None

import uuid
import json
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, status
from typing import List

from core.database import db_client, get_db
from api.deps import get_current_user
from core.security import encrypt_value
from models.schemas import ProviderCreate, ProviderUpdate, ProviderResponse

router = APIRouter()

VALID_PROVIDER_TYPES = {'groq', 'openai', 'deepgram', 'elevenlabs', 'cartesia', 'sarvam'}

def verify_org_access(current_user: dict, org_id: str, require_admin: bool = False):
    if current_user.get("org_id") != org_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to access this organization"
        )
    if require_admin and current_user.get("role") != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only administrators can manage providers"
        )

@router.get("", response_model=List[ProviderResponse])
async def get_providers(
    org_id: str,
    current_user: dict = Depends(get_current_user),
    db=Depends(get_db)
):
    verify_org_access(current_user, org_id)
    
    # We explicitly omit 'api_key' from the SELECT statement so it is never returned
    rows = await db_client.fetch_all(
        "SELECT id, org_id, name, provider_type, config, is_active, created_at FROM providers WHERE org_id = ?",
        [org_id]
    )
    
    for row in rows:
        row["config"] = json.loads(row["config"]) if row.get("config") else {}
        row["is_active"] = bool(row["is_active"])
        
    return rows

@router.post("", response_model=ProviderResponse)
async def create_provider(
    org_id: str,
    provider: ProviderCreate,
    current_user: dict = Depends(get_current_user),
    db=Depends(get_db)
):
    verify_org_access(current_user, org_id, require_admin=True)
    
    if provider.provider_type not in VALID_PROVIDER_TYPES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid provider_type. Must be one of: {', '.join(VALID_PROVIDER_TYPES)}"
        )
        
    provider_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    
    # Encrypt the sensitive API key before writing to the database
    encrypted_key = encrypt_value(provider.api_key)
    config_json = json.dumps(provider.config)
    
    await db_client.execute(
        "INSERT INTO providers (id, org_id, name, provider_type, api_key, config, is_active, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        [provider_id, org_id, provider.name, provider.provider_type, encrypted_key, config_json, True, now]
    )
    
    return ProviderResponse(
        id=provider_id,
        org_id=org_id,
        name=provider.name,
        provider_type=provider.provider_type,
        config=provider.config,
        is_active=True,
        created_at=now
    )

@router.patch("/{provider_id}", response_model=ProviderResponse)
async def update_provider(
    org_id: str,
    provider_id: str,
    update_data: ProviderUpdate,
    current_user: dict = Depends(get_current_user),
    db=Depends(get_db)
):
    verify_org_access(current_user, org_id, require_admin=True)
    
    # Omit api_key here as well
    provider = await db_client.fetch_one(
        "SELECT id, org_id, name, provider_type, config, is_active, created_at FROM providers WHERE id = ? AND org_id = ?",
        [provider_id, org_id]
    )
    if not provider:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Provider not found"
        )
        
    fields_to_update = []
    params = []
    
    if update_data.name is not None:
        fields_to_update.append("name = ?")
        params.append(update_data.name)
        provider["name"] = update_data.name
        
    if update_data.config is not None:
        current_config = json.loads(provider["config"]) if provider.get("config") else {}
        current_config.update(update_data.config)
        fields_to_update.append("config = ?")
        params.append(json.dumps(current_config))
        provider["config"] = current_config
    else:
        provider["config"] = json.loads(provider["config"]) if provider.get("config") else {}
        
    if update_data.is_active is not None:
        fields_to_update.append("is_active = ?")
        params.append(update_data.is_active)
        provider["is_active"] = update_data.is_active
        
    if fields_to_update:
        query = f"UPDATE providers SET {', '.join(fields_to_update)} WHERE id = ?"
        params.append(provider_id)
        await db_client.execute(query, params)
        
    provider["is_active"] = bool(provider["is_active"])
    
    return provider

@router.delete("/{provider_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_provider(
    org_id: str,
    provider_id: str,
    current_user: dict = Depends(get_current_user),
    db=Depends(get_db)
):
    verify_org_access(current_user, org_id, require_admin=True)
    
    provider = await db_client.fetch_one("SELECT id FROM providers WHERE id = ? AND org_id = ?", [provider_id, org_id])
    if not provider:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Provider not found"
        )
        
    await db_client.execute("DELETE FROM providers WHERE id = ?", [provider_id])
    return None

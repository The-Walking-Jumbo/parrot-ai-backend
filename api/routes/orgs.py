import json
from fastapi import APIRouter, Depends, HTTPException, status
from typing import Dict, Any

from core.database import db_client, get_db
from api.deps import get_current_user
from models.schemas import OrgResponse, OrgUpdateRequest

router = APIRouter()

@router.get("/{org_id}", response_model=OrgResponse)
async def get_organization(
    org_id: str,
    current_user: dict = Depends(get_current_user),
    db=Depends(get_db)
):
    # Verify user belongs to the org
    if current_user.get("org_id") != org_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to access this organization"
        )

    org = await db_client.fetch_one("SELECT id, name, subdomain, settings, created_at FROM organizations WHERE id = ?", [org_id])
    if not org:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Organization not found"
        )
    
    # Parse settings from JSON string
    try:
        org["settings"] = json.loads(org["settings"]) if org["settings"] else {}
    except json.JSONDecodeError:
        org["settings"] = {}

    return org

@router.patch("/{org_id}", response_model=OrgResponse)
async def update_organization(
    org_id: str,
    update_data: OrgUpdateRequest,
    current_user: dict = Depends(get_current_user),
    db=Depends(get_db)
):
    # Verify user belongs to the org
    if current_user.get("org_id") != org_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to access this organization"
        )
        
    # Only admins can update org settings
    if current_user.get("role") != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only administrators can update organization details"
        )

    org = await db_client.fetch_one("SELECT id, name, subdomain, settings, created_at FROM organizations WHERE id = ?", [org_id])
    if not org:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Organization not found"
        )

    # Parse current settings
    try:
        current_settings = json.loads(org["settings"]) if org["settings"] else {}
    except json.JSONDecodeError:
        current_settings = {}

    # Prepare update fields
    fields_to_update = []
    params = []

    if update_data.name is not None:
        fields_to_update.append("name = ?")
        params.append(update_data.name)
        org["name"] = update_data.name

    if update_data.settings is not None:
        # Merge settings, not replace
        current_settings.update(update_data.settings)
        settings_json = json.dumps(current_settings)
        fields_to_update.append("settings = ?")
        params.append(settings_json)
        org["settings"] = current_settings
    else:
        org["settings"] = current_settings

    # Perform update if there are fields to update
    if fields_to_update:
        query = f"UPDATE organizations SET {', '.join(fields_to_update)} WHERE id = ?"
        params.append(org_id)
        await db_client.execute(query, params)

    return org

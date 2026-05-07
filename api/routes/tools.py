import uuid
import json
from typing import List
from fastapi import APIRouter, Depends, HTTPException, status

from core.database import db_client, get_db
from api.deps import get_current_user
from models.schemas import ToolCreate, ToolUpdate, ToolResponse

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
            detail="Only administrators can manage tools"
        )

def validate_tool_config(tool_type: str, config: dict, is_post_call: bool):
    if tool_type == "http_request":
        if "url" not in config or "method" not in config:
            raise ValueError("http_request requires 'url' and 'method' in config")
    elif tool_type == "database_query":
        if "connection_string" not in config or "query" not in config:
            raise ValueError("database_query requires 'connection_string' and 'query' in config")
    elif tool_type == "email_send":
        if not is_post_call:
            raise ValueError("email_send is only supported for post-call tools")
        required_keys = ["smtp_host", "smtp_port", "from_email", "to_email", "subject", "body_template"]
        if any(k not in config for k in required_keys):
            raise ValueError(f"email_send requires: {', '.join(required_keys)}")
    elif tool_type == "crm_update":
        if not is_post_call:
            raise ValueError("crm_update is only supported for post-call tools")
    else:
        raise ValueError(f"Unsupported tool type: {tool_type}")

# =======================
# Pre-Call Tools
# =======================

@router.get("/assistants/{assistant_id}/pre-call-tools", response_model=List[ToolResponse])
async def list_pre_call_tools(
    org_id: str,
    assistant_id: str,
    current_user: dict = Depends(get_current_user),
    db=Depends(get_db)
):
    verify_org_access(current_user, org_id)
    
    rows = await db_client.fetch_all(
        "SELECT id, name, tool_type, config, execution_order, is_active FROM pre_call_tools WHERE org_id = ? AND assistant_id = ? ORDER BY execution_order ASC",
        [org_id, assistant_id]
    )
    for row in rows:
        row["config"] = json.loads(row["config"]) if row.get("config") else {}
        row["is_active"] = bool(row["is_active"])
    return rows

@router.post("/assistants/{assistant_id}/pre-call-tools", response_model=ToolResponse)
async def create_pre_call_tool(
    org_id: str,
    assistant_id: str,
    request: ToolCreate,
    current_user: dict = Depends(get_current_user),
    db=Depends(get_db)
):
    verify_org_access(current_user, org_id, require_admin=True)
    
    # Validate assistant exists
    assistant = await db_client.fetch_one("SELECT id FROM assistants WHERE id = ? AND org_id = ?", [assistant_id, org_id])
    if not assistant:
        raise HTTPException(status_code=404, detail="Assistant not found")
        
    try:
        validate_tool_config(request.tool_type, request.config, is_post_call=False)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
        
    tool_id = str(uuid.uuid4())
    config_json = json.dumps(request.config)
    
    await db_client.execute(
        """INSERT INTO pre_call_tools 
           (id, org_id, assistant_id, name, tool_type, config, execution_order, is_active) 
           VALUES (?, ?, ?, ?, ?, ?, ?, 1)""",
        [tool_id, org_id, assistant_id, request.name, request.tool_type, config_json, request.execution_order]
    )
    
    return ToolResponse(
        id=tool_id,
        name=request.name,
        tool_type=request.tool_type,
        config=request.config,
        execution_order=request.execution_order,
        is_active=True
    )

@router.patch("/pre-call-tools/{tool_id}", response_model=ToolResponse)
async def update_pre_call_tool(
    org_id: str,
    tool_id: str,
    update_data: ToolUpdate,
    current_user: dict = Depends(get_current_user),
    db=Depends(get_db)
):
    verify_org_access(current_user, org_id, require_admin=True)
    
    tool = await db_client.fetch_one("SELECT * FROM pre_call_tools WHERE id = ? AND org_id = ?", [tool_id, org_id])
    if not tool:
        raise HTTPException(status_code=404, detail="Tool not found")
        
    tool_type = update_data.tool_type or tool["tool_type"]
    current_config = json.loads(tool["config"]) if tool.get("config") else {}
    
    if update_data.config is not None:
        current_config.update(update_data.config)
        
    try:
        validate_tool_config(tool_type, current_config, is_post_call=False)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
        
    fields = []
    params = []
    
    if update_data.name is not None:
        fields.append("name = ?")
        params.append(update_data.name)
        tool["name"] = update_data.name
    if update_data.tool_type is not None:
        fields.append("tool_type = ?")
        params.append(update_data.tool_type)
        tool["tool_type"] = update_data.tool_type
    if update_data.config is not None:
        fields.append("config = ?")
        params.append(json.dumps(current_config))
    if update_data.execution_order is not None:
        fields.append("execution_order = ?")
        params.append(update_data.execution_order)
        tool["execution_order"] = update_data.execution_order
    if update_data.is_active is not None:
        fields.append("is_active = ?")
        params.append(update_data.is_active)
        tool["is_active"] = update_data.is_active
        
    if fields:
        query = f"UPDATE pre_call_tools SET {', '.join(fields)} WHERE id = ?"
        params.append(tool_id)
        await db_client.execute(query, params)
        
    tool["config"] = current_config
    tool["is_active"] = bool(tool["is_active"])
    
    return tool

@router.delete("/pre-call-tools/{tool_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_pre_call_tool(
    org_id: str,
    tool_id: str,
    current_user: dict = Depends(get_current_user),
    db=Depends(get_db)
):
    verify_org_access(current_user, org_id, require_admin=True)
    await db_client.execute("DELETE FROM pre_call_tools WHERE id = ? AND org_id = ?", [tool_id, org_id])
    return None

# =======================
# Post-Call Tools
# =======================

@router.get("/assistants/{assistant_id}/post-call-tools", response_model=List[ToolResponse])
async def list_post_call_tools(
    org_id: str,
    assistant_id: str,
    current_user: dict = Depends(get_current_user),
    db=Depends(get_db)
):
    verify_org_access(current_user, org_id)
    
    rows = await db_client.fetch_all(
        "SELECT id, name, tool_type, config, execution_order, is_active FROM post_call_tools WHERE org_id = ? AND assistant_id = ? ORDER BY execution_order ASC",
        [org_id, assistant_id]
    )
    for row in rows:
        row["config"] = json.loads(row["config"]) if row.get("config") else {}
        row["is_active"] = bool(row["is_active"])
    return rows

@router.post("/assistants/{assistant_id}/post-call-tools", response_model=ToolResponse)
async def create_post_call_tool(
    org_id: str,
    assistant_id: str,
    request: ToolCreate,
    current_user: dict = Depends(get_current_user),
    db=Depends(get_db)
):
    verify_org_access(current_user, org_id, require_admin=True)
    
    assistant = await db_client.fetch_one("SELECT id FROM assistants WHERE id = ? AND org_id = ?", [assistant_id, org_id])
    if not assistant:
        raise HTTPException(status_code=404, detail="Assistant not found")
        
    try:
        validate_tool_config(request.tool_type, request.config, is_post_call=True)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
        
    tool_id = str(uuid.uuid4())
    config_json = json.dumps(request.config)
    
    await db_client.execute(
        """INSERT INTO post_call_tools 
           (id, org_id, assistant_id, name, tool_type, config, execution_order, is_active) 
           VALUES (?, ?, ?, ?, ?, ?, ?, 1)""",
        [tool_id, org_id, assistant_id, request.name, request.tool_type, config_json, request.execution_order]
    )
    
    return ToolResponse(
        id=tool_id,
        name=request.name,
        tool_type=request.tool_type,
        config=request.config,
        execution_order=request.execution_order,
        is_active=True
    )

@router.patch("/post-call-tools/{tool_id}", response_model=ToolResponse)
async def update_post_call_tool(
    org_id: str,
    tool_id: str,
    update_data: ToolUpdate,
    current_user: dict = Depends(get_current_user),
    db=Depends(get_db)
):
    verify_org_access(current_user, org_id, require_admin=True)
    
    tool = await db_client.fetch_one("SELECT * FROM post_call_tools WHERE id = ? AND org_id = ?", [tool_id, org_id])
    if not tool:
        raise HTTPException(status_code=404, detail="Tool not found")
        
    tool_type = update_data.tool_type or tool["tool_type"]
    current_config = json.loads(tool["config"]) if tool.get("config") else {}
    
    if update_data.config is not None:
        current_config.update(update_data.config)
        
    try:
        validate_tool_config(tool_type, current_config, is_post_call=True)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
        
    fields = []
    params = []
    
    if update_data.name is not None:
        fields.append("name = ?")
        params.append(update_data.name)
        tool["name"] = update_data.name
    if update_data.tool_type is not None:
        fields.append("tool_type = ?")
        params.append(update_data.tool_type)
        tool["tool_type"] = update_data.tool_type
    if update_data.config is not None:
        fields.append("config = ?")
        params.append(json.dumps(current_config))
    if update_data.execution_order is not None:
        fields.append("execution_order = ?")
        params.append(update_data.execution_order)
        tool["execution_order"] = update_data.execution_order
    if update_data.is_active is not None:
        fields.append("is_active = ?")
        params.append(update_data.is_active)
        tool["is_active"] = update_data.is_active
        
    if fields:
        query = f"UPDATE post_call_tools SET {', '.join(fields)} WHERE id = ?"
        params.append(tool_id)
        await db_client.execute(query, params)
        
    tool["config"] = current_config
    tool["is_active"] = bool(tool["is_active"])
    
    return tool

@router.delete("/post-call-tools/{tool_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_post_call_tool(
    org_id: str,
    tool_id: str,
    current_user: dict = Depends(get_current_user),
    db=Depends(get_db)
):
    verify_org_access(current_user, org_id, require_admin=True)
    await db_client.execute("DELETE FROM post_call_tools WHERE id = ? AND org_id = ?", [tool_id, org_id])
    return None

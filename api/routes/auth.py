import uuid
import json
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, status
from cryptography.fernet import Fernet

from core.database import db_client, get_db
from core.security import (
    hash_password,
    verify_password,
    create_access_token,
    create_refresh_token,
    decode_token,
    encrypt_value,
)
from models.schemas import (
    RegisterRequest,
    LoginRequest,
    RefreshRequest,
    TokenResponse,
)

router = APIRouter()

@router.post("/register", response_model=TokenResponse)
async def register(request: RegisterRequest, db=Depends(get_db)):
    # 1. Check if email already exists
    existing_user = await db_client.fetch_one("SELECT id FROM users WHERE email = ?", [request.email])
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email already registered"
        )
    
    # 2. Check if subdomain is taken
    existing_org = await db_client.fetch_one("SELECT id FROM organizations WHERE subdomain = ?", [request.org_subdomain])
    if existing_org:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Subdomain already taken"
        )
    
    # Generate UUIDs
    org_id = str(uuid.uuid4())
    user_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    
    # 3. Generate org encryption key
    org_encryption_key = Fernet.generate_key().decode()
    
    # 4. Hash password
    hashed_password = hash_password(request.password)
    
    # Encrypt the org specific encryption key using the master Fernet key before storing
    encrypted_org_key = encrypt_value(org_encryption_key)
    
    # 5. Insert org first
    org_settings = json.dumps({"encryption_key": encrypted_org_key})
    
    await db_client.execute(
        "INSERT INTO organizations (id, name, subdomain, settings, created_at) VALUES (?, ?, ?, ?, ?)",
        [org_id, request.org_name, request.org_subdomain, org_settings, now]
    )
    
    # Then insert user
    await db_client.execute(
        "INSERT INTO users (id, org_id, email, password_hash, full_name, role, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
        [user_id, org_id, request.email, hashed_password, request.full_name, "admin", now]
    )
    
    # 6. Generate tokens
    token_data = {"sub": request.email, "org_id": org_id, "user_id": user_id, "role": "admin"}
    access_token = create_access_token(data=token_data)
    refresh_token = create_refresh_token(data=token_data)
    
    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        user={"id": user_id, "email": request.email, "org_id": org_id, "role": "admin", "full_name": request.full_name},
        org={"id": org_id, "name": request.org_name, "subdomain": request.org_subdomain}
    )

@router.post("/login", response_model=TokenResponse)
async def login(request: LoginRequest, db=Depends(get_db)):
    # 1. Find user by email
    user = await db_client.fetch_one("SELECT id, org_id, email, password_hash, full_name, role FROM users WHERE email = ?", [request.email])
    
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials"
        )
        
    # 2. Verify password
    if not verify_password(request.password, user["password_hash"]):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials"
        )
        
    # Fetch org info
    org = await db_client.fetch_one("SELECT id, name, subdomain FROM organizations WHERE id = ?", [user["org_id"]])
    
    # 3. Generate tokens
    token_data = {"sub": user["email"], "org_id": user["org_id"], "user_id": user["id"], "role": user["role"]}
    access_token = create_access_token(data=token_data)
    refresh_token = create_refresh_token(data=token_data)
    
    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        user={"id": user["id"], "email": user["email"], "org_id": user["org_id"], "role": user["role"], "full_name": user["full_name"]},
        org={"id": org["id"], "name": org["name"], "subdomain": org["subdomain"]} if org else None
    )

@router.post("/refresh", response_model=TokenResponse)
async def refresh(request: RefreshRequest, db=Depends(get_db)):
    # Verify refresh token
    payload = decode_token(request.refresh_token)
    
    if not payload or payload.get("type") != "refresh":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired refresh token"
        )
        
    email = payload.get("sub")
    org_id = payload.get("org_id")
    user_id = payload.get("user_id")
    role = payload.get("role")
    
    if not email:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token payload"
        )
        
    # Generate new access token
    token_data = {"sub": email, "org_id": org_id, "user_id": user_id, "role": role}
    access_token = create_access_token(data=token_data)
    
    return TokenResponse(
        access_token=access_token,
        refresh_token=request.refresh_token, # keep the same refresh token
        user={"id": user_id, "email": email, "org_id": org_id, "role": role}
    )

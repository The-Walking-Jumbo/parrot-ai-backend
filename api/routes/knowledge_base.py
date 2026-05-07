import uuid
import json
import io
import logging
from datetime import datetime, timezone
from typing import List

import asyncio
from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File, Form

from core.database import db_client, get_db
from api.deps import get_current_user
from core.storage import gcs_client
from utils.embedding import generate_embedding, cosine_similarity
from models.schemas import KBDocumentResponse, KBSearchRequest, KBSearchResponse

logger = logging.getLogger(__name__)
router = APIRouter()

ALLOWED_EXTENSIONS = {'.pdf', '.txt', '.md', '.docx'}
MAX_FILE_SIZE = 10 * 1024 * 1024  # 10 MB

def verify_org_access(current_user: dict, org_id: str, require_admin: bool = False):
    if current_user.get("org_id") != org_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to access this organization"
        )
    if require_admin and current_user.get("role") != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only administrators can manage the knowledge base"
        )

def extract_text_from_file(file_content: bytes, filename: str) -> str:
    """Extract text from supported file types"""
    ext = filename.lower()
    text = ""
    
    try:
        if ext.endswith('.pdf'):
            import PyPDF2
            reader = PyPDF2.PdfReader(io.BytesIO(file_content))
            for page in reader.pages:
                text += page.extract_text() + "\n"
                
        elif ext.endswith('.docx'):
            import docx
            doc = docx.Document(io.BytesIO(file_content))
            for para in doc.paragraphs:
                text += para.text + "\n"
                
        elif ext.endswith('.txt') or ext.endswith('.md'):
            text = file_content.decode('utf-8')
            
    except Exception as e:
        logger.error(f"Error extracting text from {filename}: {e}")
        raise ValueError(f"Failed to extract text from file: {str(e)}")
        
    return text.strip()

@router.get("", response_model=List[KBDocumentResponse])
async def list_documents(
    org_id: str,
    current_user: dict = Depends(get_current_user),
    db=Depends(get_db)
):
    verify_org_access(current_user, org_id)
    
    rows = await db_client.fetch_all(
        "SELECT id, org_id, title, content, file_url, file_type, status, created_at FROM knowledge_base WHERE org_id = ?",
        [org_id]
    )
    return rows

@router.post("", response_model=KBDocumentResponse)
async def upload_document(
    org_id: str,
    title: str = Form(...),
    file: UploadFile = File(...),
    current_user: dict = Depends(get_current_user),
    db=Depends(get_db)
):
    verify_org_access(current_user, org_id, require_admin=True)
    
    # 1. Validate file type
    filename = file.filename or ""
    ext = ""
    for allowed_ext in ALLOWED_EXTENSIONS:
        if filename.lower().endswith(allowed_ext):
            ext = allowed_ext
            break
            
    if not ext:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, 
            detail=f"Unsupported file type. Allowed: {', '.join(ALLOWED_EXTENSIONS)}"
        )
        
    # 2. Validate file size
    file_content = await file.read()
    if len(file_content) > MAX_FILE_SIZE:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, 
            detail="File size exceeds 10MB limit"
        )
        
    doc_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    
    # 3. Upload to GCS
    destination_path = f"{org_id}/documents/{doc_id}{ext}"
    try:
        file_url = await asyncio.to_thread(gcs_client.upload_file, file_content, destination_path, file.content_type)
    except Exception as e:
        logger.error(f"GCS upload failed: {e}")
        raise HTTPException(status_code=500, detail="Failed to upload file to storage")

    # 4. Extract text content
    try:
        text_content = await asyncio.to_thread(extract_text_from_file, file_content, filename)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
        
    if not text_content:
        raise HTTPException(status_code=400, detail="Could not extract any text from the file")

    # Save initial state as processing
    await db_client.execute(
        """INSERT INTO knowledge_base 
           (id, org_id, title, content, file_url, file_type, status, embedding, created_at) 
           VALUES (?, ?, ?, ?, ?, ?, 'processing', NULL, ?)""",
        [doc_id, org_id, title, text_content, file_url, ext.lstrip('.'), now]
    )
    
    # 5. Generate embedding (doing this synchronously for now, in prod should be background task)
    try:
        embedding_vec = await asyncio.to_thread(generate_embedding, text_content)
        embedding_json = json.dumps(embedding_vec)
        
        # 6. Update database with embedding and set status='ready'
        await db_client.execute(
            "UPDATE knowledge_base SET embedding = ?, status = 'ready' WHERE id = ?",
            [embedding_json, doc_id]
        )
        status_val = 'ready'
    except Exception as e:
        logger.error(f"Embedding generation failed for {doc_id}: {e}")
        await db_client.execute("UPDATE knowledge_base SET status = 'error' WHERE id = ?", [doc_id])
        status_val = 'error'

    return KBDocumentResponse(
        id=doc_id,
        org_id=org_id,
        title=title,
        content=text_content[:500] + "..." if len(text_content) > 500 else text_content, # Return snippet
        file_url=file_url,
        file_type=ext.lstrip('.'),
        status=status_val,
        created_at=now
    )

@router.post("/search", response_model=List[KBSearchResponse])
async def search_knowledge_base(
    org_id: str,
    request: KBSearchRequest,
    current_user: dict = Depends(get_current_user),
    db=Depends(get_db)
):
    verify_org_access(current_user, org_id)
    
    # 1. Generate embedding for query
    try:
        query_embedding = await asyncio.to_thread(generate_embedding, request.query)
    except Exception as e:
        raise HTTPException(status_code=500, detail="Failed to generate query embedding")
        
    # 2. Fetch all ready documents for org
    rows = await db_client.fetch_all(
        "SELECT id, title, content, embedding FROM knowledge_base WHERE org_id = ? AND status = 'ready' AND embedding IS NOT NULL",
        [org_id]
    )
    
    if not rows:
        return []
        
    # 3. Calculate cosine similarity
    results = []
    for row in rows:
        try:
            doc_embedding = json.loads(row["embedding"])
            score = cosine_similarity(query_embedding, doc_embedding)
            results.append({
                "id": row["id"],
                "title": row["title"],
                "content": row["content"],
                "relevance_score": score
            })
        except Exception as e:
            logger.warning(f"Failed to calculate similarity for doc {row['id']}: {e}")
            continue
            
    # 4. Return top_k results sorted by relevance
    results.sort(key=lambda x: x["relevance_score"], reverse=True)
    top_results = results[:request.top_k]
    
    return [KBSearchResponse(**res) for res in top_results]

@router.delete("/{doc_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_document(
    org_id: str,
    doc_id: str,
    current_user: dict = Depends(get_current_user),
    db=Depends(get_db)
):
    verify_org_access(current_user, org_id, require_admin=True)
    
    doc = await db_client.fetch_one("SELECT id, file_type FROM knowledge_base WHERE id = ? AND org_id = ?", [doc_id, org_id])
    if not doc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found")
        
    # Delete from GCS
    ext = f".{doc['file_type']}" if doc['file_type'] else ""
    destination_path = f"{org_id}/documents/{doc_id}{ext}"
    try:
        await asyncio.to_thread(gcs_client.delete_file, destination_path)
    except Exception as e:
        logger.warning(f"Failed to delete file from GCS {destination_path}: {e}")
        
    # Delete from DB
    await db_client.execute("DELETE FROM knowledge_base WHERE id = ?", [doc_id])
    
    return None

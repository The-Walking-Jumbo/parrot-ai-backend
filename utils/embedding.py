from openai import OpenAI
import numpy as np
import logging
from core.config import settings

logger = logging.getLogger(__name__)

# Initialize the synchronous OpenAI client
client = OpenAI(api_key=settings.OPENAI_API_KEY)

def generate_embedding(text: str) -> list:
    """Generate embedding using OpenAI text-embedding-3-small"""
    if not settings.OPENAI_API_KEY:
        logger.warning("OPENAI_API_KEY is not set. Cannot generate embeddings.")
        # Return a dummy vector of the correct size (1536 for text-embedding-3-small) if key is missing
        # This is just a fallback to prevent crashes if OpenAI isn't configured in dev
        return [0.0] * 1536
        
    try:
        response = client.embeddings.create(
            model="text-embedding-3-small",
            input=text
        )
        return response.data[0].embedding
    except Exception as e:
        logger.error(f"Failed to generate embedding: {e}")
        raise

def cosine_similarity(vec1: list, vec2: list) -> float:
    """Calculate cosine similarity between two vectors"""
    v1 = np.array(vec1)
    v2 = np.array(vec2)
    
    norm1 = np.linalg.norm(v1)
    norm2 = np.linalg.norm(v2)
    
    if norm1 == 0 or norm2 == 0:
        return 0.0
        
    return float(np.dot(v1, v2) / (norm1 * norm2))

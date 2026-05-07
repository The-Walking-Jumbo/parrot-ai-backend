from google.cloud import storage
from datetime import timedelta
from core.config import settings
import logging

logger = logging.getLogger(__name__)

class GCSClient:
    def __init__(self):
        # Service account key is loaded from GOOGLE_APPLICATION_CREDENTIALS env var
        # or defaults to standard GCP auth flow if not set
        self.bucket_name = settings.GCS_BUCKET_NAME
        try:
            self.client = storage.Client()
            self.bucket = self.client.bucket(self.bucket_name)
        except Exception as e:
            logger.error(f"Failed to initialize GCS client: {e}")
            self.client = None
            self.bucket = None
    
    def upload_file(self, file_data: bytes, destination_path: str, content_type: str) -> str:
        """Upload file and return public URL"""
        if not self.bucket:
            raise RuntimeError("GCS Client not initialized")
            
        blob = self.bucket.blob(destination_path)
        blob.upload_from_string(file_data, content_type=content_type)
        
        # Make blob publicly readable (or use signed URLs for private)
        blob.make_public()
        
        return blob.public_url
    
    def delete_file(self, file_path: str):
        """Delete a file from GCS"""
        if not self.bucket:
            return
            
        blob = self.bucket.blob(file_path)
        if blob.exists():
            blob.delete()
    
    def generate_signed_url(self, blob_name: str, expiration_minutes: int = 60) -> str:
        """Generate a signed URL for private files"""
        if not self.bucket:
            raise RuntimeError("GCS Client not initialized")
            
        blob = self.bucket.blob(blob_name)
        url = blob.generate_signed_url(
            expiration=timedelta(minutes=expiration_minutes),
            method='GET'
        )
        return url

gcs_client = GCSClient()

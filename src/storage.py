import json
import io

from dataclasses import dataclass
from minio import Minio
from structlog import get_logger

from src.config import get_settings

logger = get_logger(__name__)
settings = get_settings()

@dataclass
class DocumentUrls:
    content_url: str
    images_url: dict[str, str]

class MDStorage:
    
    def __init__(self) -> None:
        self._client = Minio(
            endpoint=f"{settings.minio_host}:{settings.minio_port}",
            access_key=settings.minio_access_key,
            secret_key=settings.minio_secret_key,
            secure=False, # falso pra http e true para https
        )
        
        if not self._client.bucket_exists(settings.minio_bucket):
            self._client.make_bucket(settings.minio_bucket)
            logger.info("minio_bucket_created", bucket=settings.minio_bucket)
        
        self._set_public_read_policy()
        
        
    def _set_public_read_policy(self) -> None:
        policy = {
            "Version": "2012-10-17",
            "Statement":[{
                "Effect": "Allow", # permite acessos publicos
                "Principal": {"AWS": ["*"]}, # qualquer usuario
                "Action": ["s3:GetObject"], # permite apenas leitura
                "Resource": [f"arn:aws:s3:::{settings.minio_bucket}/*"] # aplica a politica a todos os objetos do bucket
            }]
        }
        self._client.set_bucket_policy(settings.minio_bucket, json.dumps(policy))
    
    def _put(self, object_name: str, data: bytes, content_type: str) -> None:
        try:
            self._client.put_object(
                bucket_name=settings.minio_bucket,
                object_name=object_name,
                data=io.BytesIO(data),
                length=len(data),
                content_type=content_type,
            )
            logger.info("object_uploaded", bucket=settings.minio_bucket, object_name=object_name)
        except Exception as e:
            logger.error("object_upload_failed", bucket=settings.minio_bucket, object_name=object_name, error=str(e))
            raise 
    
    def upload_document(self, job_id: str, markdown: str, images: dict[str, bytes]) -> DocumentUrls:
        images_url = {}
        for name, data in images.items():
            self._put(
                object_name=f"{job_id}/images/{name}",
                data=data,
                content_type="image/png",
            )
            images_url[name] = f"{settings.minio_public_url}/{settings.minio_bucket}/{job_id}/images/{name}"
            
        for name, url in images_url.items():
            markdown = markdown.replace(f"]({name})", f"]({url})")
        
        
        self._put(
            object_name=f"{job_id}/document.md",
            data=markdown.encode("utf-8"),
            content_type="text/markdown; charset=utf-8",
        )
        
        content_url = f"{settings.minio_public_url}/{settings.minio_bucket}/{job_id}/document.md"
        logger.debug("document_uploaded", job_id=job_id, content_url=content_url, images_url=images_url)
        return DocumentUrls(content_url=content_url, images_url=images_url)

    def delete_document(self, job_id: str) -> None:
        try:
            objects_to_delete = self._client.list_objects(settings.minio_bucket, prefix=f"{job_id}/", recursive=True)
            for obj in objects_to_delete:
                self._client.remove_object(settings.minio_bucket, obj.object_name)
                logger.info("object_deleted", bucket=settings.minio_bucket, object_name=obj.object_name)
        except Exception as e:
            logger.error("document_deletion_failed", job_id=job_id, error=str(e))
            raise
import structlog
import tempfile
import hashlib
from marker.converters.pdf import PdfConverter
from marker.models import create_model_dict
from pathlib import Path


from src.schemas import Document, DocumentType

logger = structlog.get_logger(__name__)

class PDFExtractor:
    
    def __init__(self) -> None:
        self._converter = PdfConverter(artifact_dict=create_model_dict())
        logger.info("PDFExtractor initialized")
        
    def extract(self, pdf_bytes: bytes, source: str) -> Document:
        
        if not pdf_bytes:
            raise ValueError("PDF bytes cannot be empty")
        
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as temp_pdf:
            temp_pdf.write(pdf_bytes)
            temp_path = Path(temp_pdf.name)
            
            logger.info("extracting_pdf", source=source, extracted_length=len(pdf_bytes))
            
            try:
                rendered = self._converter(str(temp_path))
                markdown_content = rendered.markdown
            except Exception as e:
                logger.error("Error during PDF conversion", error=str(e))
                raise RuntimeError(f"Failed to convert PDF: {e}") from e
            finally:
                temp_path.unlink(missing_ok=True)
            
            if not markdown_content or not markdown_content.strip():
                raise RuntimeError("Extracted markdown content is empty")
            
            doc_id = hashlib.sha256(pdf_bytes).hexdigest()[:16] # detect duplicates by hashing the content
            title = self._extract_title(markdown_content, fallback=source)
            
            metadata: dict = {"source_size_bytes": len(pdf_bytes)}
            if hasattr(rendered, "metadata") and rendered.metadata:
                metadata["pdf_metadata"] = rendered.metadata
            
            document = Document(
                doc_id=doc_id,
                title=title,
                content=markdown_content,
                doc_type=DocumentType.PDF,
                source=source,
                metadata=metadata
            )
            
            return document
    
    def _extract_title(self,markdown: str, fallback: str) -> str:
        
        for line in markdown.splitlines():
            stripped = line.strip()
            if stripped.startswith("# "):
                return stripped.removeprefix("# ").strip()
        return fallback
            
import structlog
import tempfile
import hashlib
from marker.converters.pdf import PdfConverter
from marker.models import create_model_dict
from pathlib import Path


from src.schemas import Document

logger = structlog.get_logger(__name__)

class PDFConverter:
    """Converts PDF files to Markdown using Marker."""

    def __init__(self, torch_device: str) -> None:
        """Initialize the converter and load Marker models."""
        config = {"device": torch_device}
        self._converter = PdfConverter(artifact_dict=create_model_dict(device=torch_device), config=config)
        
        logger.info("PDFExtractor initialized", torch_device=torch_device)
        
    def convert(self, pdf_bytes: bytes, source: str, job_id: str) -> Document:
        """Convert PDF bytes to a Document with Markdown content."""
        
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
            
            content_hash = hashlib.sha256(pdf_bytes).hexdigest()[:16] # detect duplicates by hashing the content
            title = self._extract_title(markdown_content, fallback=source)
            
            metadata: dict = {"source_size_bytes": len(pdf_bytes)}
            if hasattr(rendered, "metadata") and rendered.metadata:
                metadata["pdf_metadata"] = rendered.metadata
            
            document = Document(
                job_id=job_id,
                content_hash=content_hash,
                title=title,
                content=markdown_content,
                source=source,
                metadata=metadata
            )
            
            return document
    
    def _extract_title(self,markdown: str, fallback: str) -> str:
        """Extract the first H1 heading from markdown, or return fallback."""
        
        for line in markdown.splitlines():
            stripped = line.strip()
            if stripped.startswith("# "):
                return stripped.removeprefix("# ").strip()
        return fallback
            
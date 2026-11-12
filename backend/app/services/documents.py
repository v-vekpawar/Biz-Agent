"""UploadedDocument use cases (validations + durable storage metadata)."""

from __future__ import annotations

import inspect
import uuid
import zipfile
from pathlib import Path
from typing import Any

from ..core import config as core_config
from ..domain.enums import DocumentProcessingStatus
from ..domain.models import BusinessCase, UploadedDocument
from ..repositories import UploadRepository

_CHUNK = 1024 * 1024  # 1MB


class DocumentRejection(Exception):
    """Upload rejected by validation (wrong type, too large, ...)."""

    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.status_code = status_code


class DocumentService:
    def __init__(self, upload_repository: UploadRepository, case: BusinessCase):
        self._uploads = upload_repository
        self._case = case

    async def save_upload(self, filename: str | None, content_type: str | None, read_chunk) -> UploadedDocument:
        """Stream an upload to disk (validated+size-capped) and register it.

        `read_chunk(size) -> bytes` abstracts the transport (UploadFile or
        tests' fakes); async transports are awaited transparently. Storage
        layout: documents/{case_id}/{uuid}{safe_ext}. The DB stores a RELATIVE
        storage_reference; absolute paths never cross the API (SYSTEM_DESIGN §12).
        """
        original = (filename or "").strip() or "untitled"
        ext = Path(original).suffix.lower()
        if ext not in core_config.ALLOWED_DOCUMENT_EXTENSIONS:
            allowed = ", ".join(sorted(core_config.ALLOWED_DOCUMENT_EXTENSIONS))
            raise DocumentRejection(f"File type '{ext or original}' is not supported. Allowed: {allowed}")

        max_bytes = core_config.upload_max_bytes()
        stored_name = f"{uuid.uuid4().hex[:12]}{ext}"
        root = core_config.uploads_dir()
        target_dir = root / "documents" / str(self._case.id)
        target_dir.mkdir(parents=True, exist_ok=True)
        target = target_dir / stored_name

        size = 0
        try:
            with open(target, "wb") as out:
                while True:
                    chunk = read_chunk(_CHUNK)
                    if inspect.isawaitable(chunk):
                        chunk = await chunk
                    if not chunk:
                        break
                    size += len(chunk)
                    if size > max_bytes:
                        raise DocumentRejection(
                            f"Upload exceeds the {max_bytes} byte limit.", status_code=413
                        )
                    out.write(chunk)
        except DocumentRejection:
            target.unlink(missing_ok=True)
            raise
        except OSError as exc:
            if target.exists():
                target.unlink(missing_ok=True)
            raise DocumentRejection(f"Could not store the upload: {exc}", status_code=500)

        # Extension is not a trust boundary: validate container signatures for
        # binary formats before registering metadata. Never accept a renamed
        # executable/script as an Office or PDF document.
        try:
            if ext == ".pdf":
                with open(target, "rb") as check:
                    if not check.read(5).startswith(b"%PDF-"):
                        raise DocumentRejection("The uploaded file is not a valid PDF.")
            elif ext in {".docx", ".xlsx"}:
                if not zipfile.is_zipfile(target):
                    raise DocumentRejection(f"The uploaded file is not a valid {ext[1:].upper()} container.")
                required = "word/document.xml" if ext == ".docx" else "xl/workbook.xml"
                with zipfile.ZipFile(target) as archive:
                    if required not in archive.namelist():
                        raise DocumentRejection(f"The uploaded file is missing required {ext[1:].upper()} content.")
        except DocumentRejection:
            target.unlink(missing_ok=True)
            raise
        except (OSError, zipfile.BadZipFile):
            target.unlink(missing_ok=True)
            raise DocumentRejection("The uploaded document is corrupt or unreadable.")

        reference = core_config.document_storage_reference(self._case.id, stored_name)
        return self._uploads.register(
            self._case.id,
            original,
            reference,
            mime_type=content_type,
            size_bytes=size,
            processing_status=DocumentProcessingStatus.PENDING,
        )

    def delete_stored_file(self, document: UploadedDocument) -> bool:
        """Best-effort removal of the stored file (DB row deletion triggers its
        own lifecycle rules)."""
        path = core_config.uploads_dir() / document.storage_reference
        try:
            path.unlink(missing_ok=True)
            return True
        except OSError:
            return False

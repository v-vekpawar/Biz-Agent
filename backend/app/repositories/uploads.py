"""UploadedDocument repository."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..domain.enums import DocumentProcessingStatus
from ..domain.models import UploadedDocument
from ._common import coerce_enum


class UploadRepository:
    def __init__(self, session: Session):
        self._s = session

    def register(
        self,
        business_case_id: int,
        original_filename: str,
        storage_reference: str,
        *,
        mime_type: str | None = None,
        size_bytes: int | None = None,
        processing_status: Any = DocumentProcessingStatus.PENDING,
    ) -> UploadedDocument:
        if not original_filename or not original_filename.strip():
            raise ValueError("original_filename must not be empty.")
        if not storage_reference or not storage_reference.strip():
            raise ValueError("storage_reference must not be empty.")
        document = UploadedDocument(
            business_case_id=business_case_id,
            original_filename=original_filename,
            storage_reference=storage_reference,
            mime_type=mime_type,
            size_bytes=size_bytes,
            processing_status=coerce_enum(processing_status, DocumentProcessingStatus, "processing_status"),
        )
        self._s.add(document)
        self._s.commit()
        self._s.refresh(document)
        return document

    def get(self, document_id: int) -> UploadedDocument | None:
        return self._s.get(UploadedDocument, document_id)

    def list_by_case(self, business_case_id: int) -> list[UploadedDocument]:
        return list(
            self._s.scalars(
                select(UploadedDocument)
                .where(UploadedDocument.business_case_id == business_case_id)
                .order_by(UploadedDocument.uploaded_at)
            )
        )

    def set_status(self, document_id: int, processing_status: Any) -> UploadedDocument | None:
        document = self.get(document_id)
        if document is None:
            return None
        document.processing_status = coerce_enum(processing_status, DocumentProcessingStatus, "processing_status")
        self._s.commit()
        self._s.refresh(document)
        return document

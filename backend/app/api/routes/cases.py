"""Business case + uploaded-document routes (PRODUCT_SPEC §6)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, UploadFile

from ..deps import (
    CaseRepository,
    UploadRepository,
    get_case_or_404,
    get_case_repo,
    get_current_user,
    get_document_service,
    get_upload_repo,
    value_error_status,
)
from ..schemas import BusinessCaseCreate, BusinessCasePatch, BusinessCaseRead, DocumentRead
from ...services.documents import DocumentService, DocumentRejection

router = APIRouter(tags=["business-cases"])


@router.post("", status_code=201, response_model=BusinessCaseRead)
def create_business_case(
    payload: BusinessCaseCreate,
    cases: CaseRepository = Depends(get_case_repo),
    user=Depends(get_current_user),
):
    data = payload.model_dump()
    try:
        return cases.create(data.pop("title"), data.pop("idea_description"), owner_id=user.id, **data)
    except ValueError as exc:
        status, detail = value_error_status(exc)
        raise HTTPException(status_code=status, detail=detail)


@router.get("", response_model=list[BusinessCaseRead])
def list_business_cases(cases: CaseRepository = Depends(get_case_repo), user=Depends(get_current_user)):
    return cases.list(owner_id=user.id)


@router.get("/{case_id}", response_model=BusinessCaseRead)
def get_business_case(case: BusinessCaseRead = Depends(get_case_or_404)):
    return case


@router.patch("/{case_id}", response_model=BusinessCaseRead)
def patch_business_case(
    payload: BusinessCasePatch,
    case=Depends(get_case_or_404),
    cases: CaseRepository = Depends(get_case_repo),
):
    """Partial update: present keys are applied (explicit nulls clear the
    optional field); absent keys are untouched."""
    fields = payload.model_dump(exclude_unset=True)
    if not fields:
        raise HTTPException(status_code=400, detail="No fields provided to update.")
    try:
        return cases.update(case.id, fields)
    except ValueError as exc:
        status, detail = value_error_status(exc)
        raise HTTPException(status_code=status, detail=detail)


@router.delete("/{case_id}", status_code=204)
def delete_business_case(case=Depends(get_case_or_404), cases: CaseRepository = Depends(get_case_repo)):
    """Deletes the idea and everything under it (research, sprints, collected signups)."""
    cases.delete(case.id)
    return None


@router.post("/{case_id}/documents", status_code=201, response_model=DocumentRead)
async def upload_document(
    file: UploadFile,
    service: DocumentService = Depends(get_document_service),
):
    try:
        return await service.save_upload(file.filename, file.content_type, file.read)
    except DocumentRejection as rejection:
        raise HTTPException(status_code=rejection.status_code, detail=str(rejection))


@router.get("/{case_id}/documents", response_model=list[DocumentRead])
def list_documents(
    case=Depends(get_case_or_404),
    uploads: UploadRepository = Depends(get_upload_repo),
):
    return uploads.list_by_case(case.id)

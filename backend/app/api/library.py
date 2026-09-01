"""Library CRUD (spec §5.1, FR1, FR2)."""
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.db import get_db
from app.schemas.library import (
    AddToLibraryRequest,
    LibraryEntryOut,
    UpdateEntryRequest,
    UpdateProgressRequest,
)
from app.services import library as svc

router = APIRouter(prefix="/library", tags=["library"])


@router.get("", response_model=list[LibraryEntryOut])
def list_library(
    status: str | None = Query(None),
    type: str | None = Query(None),
    db: Session = Depends(get_db),
) -> list:
    return svc.list_entries(db, status=status, media_type=type)


@router.post("", response_model=LibraryEntryOut, status_code=201)
def add_item(req: AddToLibraryRequest, db: Session = Depends(get_db)):
    try:
        return svc.add_to_library(db, req.item, req.status)
    except svc.AlreadyInLibrary as exc:
        raise HTTPException(status_code=409, detail="Item is already in the library") from exc


@router.get("/{entry_id}", response_model=LibraryEntryOut)
def get_item(entry_id: uuid.UUID, db: Session = Depends(get_db)):
    try:
        return svc.get_entry(db, entry_id)
    except svc.EntryNotFound as exc:
        raise HTTPException(status_code=404, detail="Library entry not found") from exc


@router.patch("/{entry_id}", response_model=LibraryEntryOut)
def update_item(
    entry_id: uuid.UUID, req: UpdateEntryRequest, db: Session = Depends(get_db)
):
    try:
        return svc.update_entry(db, entry_id, req)
    except svc.EntryNotFound as exc:
        raise HTTPException(status_code=404, detail="Library entry not found") from exc


@router.delete("/{entry_id}", status_code=204)
def remove_item(entry_id: uuid.UUID, db: Session = Depends(get_db)) -> None:
    try:
        svc.remove_from_library(db, entry_id)
    except svc.EntryNotFound as exc:
        raise HTTPException(status_code=404, detail="Library entry not found") from exc


@router.put("/{entry_id}/progress", response_model=LibraryEntryOut)
def update_item_progress(
    entry_id: uuid.UUID, req: UpdateProgressRequest, db: Session = Depends(get_db)
):
    try:
        return svc.update_progress(db, entry_id, req)
    except svc.EntryNotFound as exc:
        raise HTTPException(status_code=404, detail="Library entry not found") from exc
    except svc.NotASeries as exc:
        raise HTTPException(
            status_code=400, detail="Progress tracking applies to series only"
        ) from exc

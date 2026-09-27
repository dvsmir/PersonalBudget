import json
from typing import Annotated

from fastapi import APIRouter, File, Form, UploadFile
from sqlalchemy import select

from app.api.deps import DB, CurrentUser
from app.api.schemas import BulkRowsIn, CommitIn, ImportBatchOut, ImportRuleIO, RowPatch, SuggestIn
from app.config import get_settings
from app.db.models import ImportBatch, ImportRow, ImportRule
from app.services import categoriser, imports, migration
from app.services.common import DomainError, get_or_404

router = APIRouter(tags=["imports"])


async def _read(file: UploadFile) -> bytes:
    data = await file.read()
    if len(data) > get_settings().max_upload_mb * 1024 * 1024:
        raise DomainError("too_large", f"File larger than {get_settings().max_upload_mb} MB", status=413)
    return data


@router.post("/imports", response_model=ImportBatchOut, status_code=201)
async def upload(user: CurrentUser, db: DB, file: Annotated[UploadFile, File()],
                 source: Annotated[str | None, Form()] = None,
                 account_id: Annotated[int | None, Form()] = None) -> ImportBatch:
    data = await _read(file)
    return imports.create_batch(db, file.filename or "upload", data, user.id, source or None, account_id)


@router.post("/imports/sheet", response_model=ImportBatchOut, status_code=201)
async def upload_sheet(user: CurrentUser, db: DB, file: Annotated[UploadFile, File()],
                       years: Annotated[str | None, Form()] = None) -> ImportBatch:
    """Historical Google Sheet (xlsx export). `years`: comma-separated, e.g. '2025,2026'; empty = all."""
    data = await _read(file)
    year_set = {int(y) for y in years.split(",") if y.strip()} if years else None
    return migration.import_sheet(db, file.filename or "sheet.xlsx", data, user.id, year_set)


@router.post("/migration/anchors")
async def anchors(user: CurrentUser, db: DB, file: Annotated[UploadFile, File()]) -> dict:
    return migration.load_anchors(db, await _read(file), user.id)


@router.post("/migration/balance")
def balance(user: CurrentUser, db: DB) -> list[dict]:
    return migration.generate_balancing(db, user.id)


@router.get("/imports", response_model=list[ImportBatchOut])
def list_batches(user: CurrentUser, db: DB) -> list[ImportBatch]:
    return list(db.scalars(select(ImportBatch).order_by(ImportBatch.id.desc())))


@router.get("/imports/{batch_id}", response_model=ImportBatchOut)
def get_batch(batch_id: int, user: CurrentUser, db: DB) -> ImportBatch:
    return imports.get_batch(db, batch_id)


@router.get("/imports/{batch_id}/rows")
def rows(batch_id: int, user: CurrentUser, db: DB, status: str | None = None) -> list[dict]:
    batch = imports.get_batch(db, batch_id)
    return [imports.row_view(r) for r in batch.rows if status is None or r.status == status]


@router.patch("/imports/{batch_id}/rows/{row_id}")
def patch_row(batch_id: int, row_id: int, body: RowPatch, user: CurrentUser, db: DB) -> dict:
    row = get_or_404(db, ImportRow, row_id)
    if row.batch_id != batch_id:
        raise DomainError("not_found", "Row not in batch", status=404)
    row = imports.update_row(db, row_id, body.proposed, body.status)
    imports.refresh_stats(db, row.batch)
    return imports.row_view(row)


@router.post("/imports/{batch_id}/rows/bulk")
def bulk(batch_id: int, body: BulkRowsIn, user: CurrentUser, db: DB) -> dict:
    return {"updated": imports.bulk_update(db, batch_id, body.row_ids, body.filter, body.status, body.patch)}


@router.post("/imports/{batch_id}/suggest")
def suggest(batch_id: int, body: SuggestIn, user: CurrentUser, db: DB) -> dict:
    batch = imports.get_batch(db, batch_id)
    result = categoriser.suggest(db, batch, body.row_ids)
    imports.refresh_stats(db, batch)
    return result


@router.post("/imports/{batch_id}/commit")
def commit(batch_id: int, body: CommitIn, user: CurrentUser, db: DB) -> dict:
    return imports.commit_batch(db, batch_id, user.id, body.row_ids)


@router.delete("/imports/{batch_id}", status_code=204)
def discard(batch_id: int, user: CurrentUser, db: DB) -> None:
    imports.discard_batch(db, batch_id)


@router.get("/import-rules", response_model=list[ImportRuleIO])
def list_rules(user: CurrentUser, db: DB) -> list[ImportRule]:
    return list(db.scalars(select(ImportRule).order_by(ImportRule.source, ImportRule.priority)))


@router.put("/import-rules", response_model=list[ImportRuleIO])
def replace_rules(body: list[ImportRuleIO], user: CurrentUser, db: DB) -> list[ImportRule]:
    for r in body:
        json.loads(r.match)
        json.loads(r.action)  # validate JSON
    db.query(ImportRule).delete()
    for r in body:
        db.add(ImportRule(**r.model_dump(exclude={"id"})))
    db.flush()
    return list(db.scalars(select(ImportRule).order_by(ImportRule.source, ImportRule.priority)))

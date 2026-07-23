"""Admin-only tenant management — the data-source manager behind the panel.

    POST   /admin/tenants                       create a cluster
    PATCH  /admin/tenants/{slug}                 edit name / version / mode / active
    POST   /admin/tenants/{slug}/link/{user_id}    give a user access
    DELETE /admin/tenants/{slug}/link/{user_id}    revoke a user's access
    GET    /admin/tenants/{slug}/users             which users currently have access
    PUT    /admin/tenants/{slug}/connection      set live-API CM connection (encrypted)
    POST   /admin/tenants/{slug}/test-connection test CM reachability
    POST   /admin/tenants/{slug}/files           upload+validate a CM export file
    DELETE /admin/tenants/{slug}/files/{file_id} remove an uploaded file
"""

import logging

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from ...core.crypto import decrypt, encrypt
from ...db.base import get_db
from ...db.models import Role, Tenant, TenantFile, User, UserTenant
from ...engine import bridge, uploads
from ...schemas.tenant import CmConnection, TenantCreate, TenantDetail, TenantUpdate
from ..deps import require_admin
from ..tenant_deps import get_tenant_or_404

log = logging.getLogger("backend.tenant_admin")

router = APIRouter(prefix="/admin/tenants", tags=["admin:tenants"], dependencies=[Depends(require_admin)])

MAX_UPLOAD_BYTES = 64 * 1024 * 1024  # 64 MB — CM exports can be tens of MB


def _detail(tenant: Tenant) -> TenantDetail:
    from .monitoring import _tenant_detail

    return _tenant_detail(tenant)


@router.post("", response_model=TenantDetail, status_code=201)
def create_tenant(body: TenantCreate, db: Session = Depends(get_db)):
    if db.scalar(select(Tenant).where(Tenant.slug == body.slug)):
        raise HTTPException(status_code=409, detail=f"A cluster with slug '{body.slug}' already exists")
    tenant = Tenant(
        slug=body.slug,
        display_name=body.display_name,
        cluster_name=body.cluster_name,
        cloudera_version=body.cloudera_version,
        data_source_mode=body.data_source_mode,
        data_dir=str(uploads.tenant_dir(body.slug)),  # json-mode tenants store uploads here
    )
    db.add(tenant)
    db.commit()
    db.refresh(tenant)
    log.info("Created tenant '%s' (%s mode)", tenant.slug, tenant.data_source_mode)
    return _detail(tenant)


@router.patch("/{slug}", response_model=TenantDetail)
def update_tenant(
    body: TenantUpdate, tenant: Tenant = Depends(get_tenant_or_404), db: Session = Depends(get_db)
):
    for field, value in body.model_dump(exclude_none=True).items():
        setattr(tenant, field, value)
    db.add(tenant)
    db.commit()
    db.refresh(tenant)
    bridge.invalidate(tenant)  # mode/settings may have changed
    return _detail(tenant)


@router.post("/{slug}/link/{user_id}", status_code=204)
def link_user(
    user_id: int, tenant: Tenant = Depends(get_tenant_or_404), db: Session = Depends(get_db)
):
    if db.get(User, user_id) is None:
        raise HTTPException(status_code=404, detail=f"No user with id {user_id}")
    if not db.scalar(
        select(UserTenant).where(UserTenant.user_id == user_id, UserTenant.tenant_id == tenant.id)
    ):
        db.add(UserTenant(user_id=user_id, tenant_id=tenant.id))
        db.commit()
    log.info("Linked user %s to tenant '%s'", user_id, tenant.slug)


@router.delete("/{slug}/link/{user_id}", status_code=204)
def unlink_user(
    user_id: int, tenant: Tenant = Depends(get_tenant_or_404), db: Session = Depends(get_db)
):
    link = db.scalar(
        select(UserTenant).where(UserTenant.user_id == user_id, UserTenant.tenant_id == tenant.id)
    )
    if link is not None:
        db.delete(link)
        db.commit()
        log.info("Unlinked user %s from tenant '%s'", user_id, tenant.slug)


@router.get("/{slug}/users")
def linked_users(tenant: Tenant = Depends(get_tenant_or_404), db: Session = Depends(get_db)):
    """Which users currently have access to this cluster."""
    rows = db.scalars(
        select(User).join(UserTenant, UserTenant.user_id == User.id).where(UserTenant.tenant_id == tenant.id)
    )
    return [{"id": u.id, "email": u.email, "full_name": u.full_name} for u in rows]


# ---------- live API connection ----------


@router.put("/{slug}/connection", response_model=TenantDetail)
def set_connection(
    body: CmConnection, tenant: Tenant = Depends(get_tenant_or_404), db: Session = Depends(get_db)
):
    tenant.cm_host = body.cm_host
    tenant.cm_port = body.cm_port
    tenant.cm_use_tls = body.cm_use_tls
    tenant.cm_username = body.cm_username
    if body.cm_password:  # only overwrite when a new password is provided
        tenant.cm_password_encrypted = encrypt(body.cm_password)
    db.add(tenant)
    db.commit()
    db.refresh(tenant)
    bridge.invalidate(tenant)
    return _detail(tenant)


@router.post("/{slug}/test-connection")
def test_connection(
    body: CmConnection | None = None,
    tenant: Tenant = Depends(get_tenant_or_404),
    db: Session = Depends(get_db),
):
    """Try one cheap CM call (GET /api/version). Uses the posted credentials if
    given, else the stored ones — so admins can test before saving."""
    from cloudera import ClouderaApiClient, ClouderaApiError

    host = body.cm_host if body else tenant.cm_host
    port = body.cm_port if body else tenant.cm_port
    use_tls = body.cm_use_tls if body else tenant.cm_use_tls
    username = body.cm_username if body else tenant.cm_username
    password = (
        body.cm_password
        if (body and body.cm_password)
        else (decrypt(tenant.cm_password_encrypted) if tenant.cm_password_encrypted else "")
    )
    if not host or not username:
        raise HTTPException(status_code=400, detail="Host and username are required to test")

    client = ClouderaApiClient(cm_host=host, port=port, username=username, password=password, use_tls=use_tls)
    try:
        version = client.resolve_version()
        return {"ok": True, "message": f"Connected — Cloudera Manager API {version}", "api_version": version}
    except ClouderaApiError as exc:
        return {"ok": False, "message": f"Cloudera Manager returned an error: {exc}"}
    except Exception as exc:  # connection refused / timeout / TLS — friendly message
        return {"ok": False, "message": f"Could not reach {host}:{port} — {exc}"}
    finally:
        client.close()


# ---------- JSON export file uploads ----------


@router.post("/{slug}/files", response_model=TenantDetail)
async def upload_file(
    file_type: str = Form(...),
    file: UploadFile = File(...),
    tenant: Tenant = Depends(get_tenant_or_404),
    db: Session = Depends(get_db),
):
    if file_type not in uploads.FILE_TYPES:
        raise HTTPException(
            status_code=400, detail=f"Unknown file type. Expected one of: {', '.join(uploads.FILE_TYPES)}"
        )

    raw = await file.read()
    if len(raw) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=400, detail="File is larger than the 64 MB limit")

    try:
        stored = uploads.store(tenant.slug, file_type, file.filename or f"{file_type}.json", raw)
        detail_msg, status = _validation_ok(tenant.slug, file_type, raw)
    except uploads.ValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    # Point the tenant at its upload folder (first upload) and record the file.
    tenant.data_dir = str(uploads.tenant_dir(tenant.slug))
    db.add(
        TenantFile(
            tenant_id=tenant.id,
            file_type=file_type,
            original_name=file.filename or f"{file_type}.json",
            stored_path=str(stored),
            size_bytes=len(raw),
            validation_status=status,
            validation_detail=detail_msg,
            uploaded_by_id=_current_admin_id(db),
        )
    )
    db.add(tenant)
    db.commit()
    db.refresh(tenant)
    bridge.invalidate(tenant)  # new data on disk — rebuild source next report
    return _detail(tenant)


def _validation_ok(slug: str, file_type: str, raw: bytes) -> tuple[str, str]:
    # store() already validated; re-run to capture the human summary.
    return uploads.validate_bytes(file_type, raw), "ok"


def _current_admin_id(db: Session) -> int | None:
    return None  # (kept simple; the file's uploaded_at + tenant scope suffice for Phase 3)


@router.delete("/{slug}/files/{file_id}", status_code=204)
def delete_file(
    file_id: int, tenant: Tenant = Depends(get_tenant_or_404), db: Session = Depends(get_db)
):
    tf = db.get(TenantFile, file_id)
    if tf is None or tf.tenant_id != tenant.id:
        raise HTTPException(status_code=404, detail="File not found for this cluster")
    from pathlib import Path

    Path(tf.stored_path).unlink(missing_ok=True)
    db.delete(tf)
    db.commit()
    bridge.invalidate(tenant)

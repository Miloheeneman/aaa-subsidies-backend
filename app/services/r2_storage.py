"""Cloudflare R2 (S3-compatible) storage helpers.

Uses boto3 with a custom endpoint URL pointing at Cloudflare R2.
When R2 credentials are not configured (typical in local dev / tests),
the service falls back to a deterministic stub so the rest of the
application flow can be exercised without real cloud storage.
"""
from __future__ import annotations

import logging
import re
from typing import Optional
from uuid import UUID

import boto3
from botocore.client import Config

from app.core.config import settings

log = logging.getLogger(__name__)


_DEFAULT_PRESIGN_PUT_SECONDS = 60 * 60  # 60 min per spec
_DEFAULT_PRESIGN_GET_SECONDS = 15 * 60  # 15 min per spec


def is_configured() -> bool:
    """Return True if real R2 credentials + endpoint are set."""
    return bool(
        settings.R2_ACCESS_KEY_ID
        and settings.R2_SECRET_ACCESS_KEY
        and settings.R2_ENDPOINT_URL
        and settings.R2_BUCKET_NAME
    )


def _client():
    return boto3.client(
        "s3",
        endpoint_url=settings.R2_ENDPOINT_URL,
        aws_access_key_id=settings.R2_ACCESS_KEY_ID,
        aws_secret_access_key=settings.R2_SECRET_ACCESS_KEY,
        region_name="auto",
        config=Config(signature_version="s3v4"),
    )


_SAFE_FILENAME_RE = re.compile(r"[^A-Za-z0-9._-]")


def safe_filename(filename: str) -> str:
    """Sanitise a user-provided filename for use in object keys."""
    name = (filename or "").strip().replace(" ", "_")
    name = _SAFE_FILENAME_RE.sub("_", name)
    if not name:
        name = "upload.bin"
    return name[:200]


def build_object_key(
    *,
    organisation_id: UUID,
    aanvraag_id: UUID,
    document_id: UUID,
    filename: str,
) -> str:
    """Build the canonical R2 object key.

    Layout: `{organisation_id}/{aanvraag_id}/{document_id}/{filename}`
    """
    return (
        f"{organisation_id}/{aanvraag_id}/{document_id}/"
        f"{safe_filename(filename)}"
    )


def generate_upload_url(
    object_key: str,
    *,
    content_type: str,
    expires_in: int = _DEFAULT_PRESIGN_PUT_SECONDS,
) -> str:
    """Return a presigned PUT URL for uploading directly to R2."""
    if not is_configured():
        log.warning(
            "R2 not configured; returning stub upload URL for key=%s", object_key
        )
        return f"https://r2.local/{object_key}?presigned=stub-put"

    return _client().generate_presigned_url(
        ClientMethod="put_object",
        Params={
            "Bucket": settings.R2_BUCKET_NAME,
            "Key": object_key,
            "ContentType": content_type,
        },
        ExpiresIn=expires_in,
    )


def generate_download_url(
    object_key: str,
    *,
    expires_in: int = _DEFAULT_PRESIGN_GET_SECONDS,
    download_filename: Optional[str] = None,
) -> str:
    """Return a presigned GET URL for downloading from R2."""
    if not is_configured():
        log.warning(
            "R2 not configured; returning stub download URL for key=%s",
            object_key,
        )
        return f"https://r2.local/{object_key}?presigned=stub-get"

    params: dict[str, str] = {
        "Bucket": settings.R2_BUCKET_NAME,
        "Key": object_key,
    }
    if download_filename:
        safe = safe_filename(download_filename)
        params["ResponseContentDisposition"] = (
            f'attachment; filename="{safe}"'
        )

    return _client().generate_presigned_url(
        ClientMethod="get_object",
        Params=params,
        ExpiresIn=expires_in,
    )


def delete_object(object_key: str) -> None:
    """Delete an object from R2. No-op when R2 is not configured."""
    if not is_configured():
        log.warning(
            "R2 not configured; skipping delete for key=%s", object_key
        )
        return
    _client().delete_object(
        Bucket=settings.R2_BUCKET_NAME, Key=object_key
    )


def key_exists(object_key: str) -> bool:
    """Return True if the object exists in R2."""
    if not is_configured():
        return False
    try:
        _client().head_object(
            Bucket=settings.R2_BUCKET_NAME, Key=object_key
        )
        return True
    except Exception:  # noqa: BLE001
        return False


PENDING_MARKER = "[pending]"


def is_pending_storage_url(storage_url: Optional[str]) -> bool:
    """True if a document was presigned but not yet confirmed by the client."""
    if not storage_url:
        return False
    return storage_url.endswith("?pending=1") or storage_url.startswith("pending://")


def make_pending_url(object_key: str) -> str:
    """Storage URL convention used between presign and confirm.

    We avoid mutating the schema by encoding "pending" state in the
    storage_url itself. A subsequent confirm() rewrites it to the real
    object key.
    """
    return f"pending://{object_key}"


def make_committed_url(object_key: str) -> str:
    """Final storage URL stored after the client confirms upload."""
    return f"r2://{object_key}"


def object_key_from_storage_url(storage_url: str) -> str:
    """Reverse of make_*_url -> the canonical R2 object key."""
    if storage_url.startswith("pending://"):
        return storage_url[len("pending://") :]
    if storage_url.startswith("r2://"):
        return storage_url[len("r2://") :]
    return storage_url

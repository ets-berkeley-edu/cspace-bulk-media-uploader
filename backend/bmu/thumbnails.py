"""Thumbnails (design: User interface, Thumbnails).

Every document row starts with a thumbnail. The browser makes one for JPEG and PNG from the local file and
sends it with the file; the thumbnail step makes one for TIFF, which browsers can't draw, once the file is
staged (in AWS a Lambda on the S3 event; here the web app runs it in the background). Thumbnails are small
JPEGs written without EXIF or any other metadata, so camera details and GPS locations never reach them.
Nothing is stored for a protected file. Once a document's file is in CollectionSpace, its thumbnail comes from
CollectionSpace's own derivatives instead, and the staged thumbnail is deleted with the staged file.
"""
from __future__ import annotations

import io
import logging
import uuid

from PIL import Image, UnidentifiedImageError

log = logging.getLogger("bmu.thumbnails")

MAX_SIDE = 320  # pixels; shown at 56 px in tables and larger when clicked
MAX_BROWSER_BYTES = 300 * 1024  # a browser-made thumbnail must be small
MAX_TIFF_BYTES = 200 * 1024 * 1024  # the prototype's thumbnail step reads the whole file; bigger TIFFs show an icon
TIFF_EXTENSIONS = {"tif", "tiff"}

Image.MAX_IMAGE_PIXELS = 300_000_000  # large museum TIFFs are legitimate; still bounded against decompression bombs


class NotAnImage(ValueError):
    pass


def make_thumbnail(data: bytes) -> bytes:
    """A metadata-free JPEG no larger than MAX_SIDE on its longer side. Raises NotAnImage."""
    try:
        with Image.open(io.BytesIO(data)) as im:
            im.draft("RGB", (MAX_SIDE, MAX_SIDE))  # JPEG: decode at a reduced size
            im.thumbnail((MAX_SIDE, MAX_SIDE))
            rgb = im.convert("RGB")
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as e:
        raise NotAnImage(str(e)) from e
    out = io.BytesIO()
    rgb.save(out, "JPEG", quality=80, optimize=True)  # no exif= or icc_profile=: nothing is carried over
    return out.getvalue()


def thumb_key(tenant: str, job_id: str, n: int) -> str:
    """Under the job's staging prefix, next to the row's file (deleted with the job's files)."""
    return f"staging/{tenant}/{job_id}/{n:05d}/thumb-{uuid.uuid4().hex}"


def tiff_thumbnail_step(storage, tenant: str, job_id: str, n: int) -> None:
    """Make a TIFF's thumbnail from its staged file, unless the row is protected (or has one already)."""
    row = storage.get_row(job_id, n)
    if not row or row.get("protected") or row.get("thumbKey") or (row.get("upload") or {}).get("s") != "done":
        return
    if row.get("size", 0) > MAX_TIFF_BYTES:
        return
    try:
        body = storage.open_object(row["s3Key"], (row.get("upload") or {}).get("version") or None)
        try:
            thumb = make_thumbnail(body.read())
        finally:
            body.close()
    except Exception:  # a thumbnail is a convenience: the row shows its type icon instead
        log.warning("no thumbnail for job %s row %s", job_id, n, exc_info=True)
        return
    storage.store_thumbnail(tenant, job_id, n, thumb)

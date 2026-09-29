"""What a staged file really is, from its first bytes (design: Browser uploads, File contents): the worker
checks each file's actual type against its extension before uploading it to CollectionSpace, and fails the
document with file_type_rejected when they differ (for example a .tif that is really a JPEG)."""
from __future__ import annotations

EXT_FAMILY = {"jpg": "JPEG", "jpeg": "JPEG", "png": "PNG", "tif": "TIFF", "tiff": "TIFF", "wav": "WAV", "mp3": "MP3",
              "aac": "AAC", "mp4": "MP4", "x3d": "X3D"}
HEAD_BYTES = 64


def detect(head: bytes) -> str | None:
    """The file type its first bytes show, or None if not one the BMU accepts."""
    if head.startswith(b"\xff\xd8\xff"):
        return "JPEG"
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return "PNG"
    if head[:4] in (b"II*\x00", b"MM\x00*", b"II+\x00", b"MM\x00+"):  # TIFF and BigTIFF
        return "TIFF"
    if head[:4] == b"RIFF" and head[8:12] == b"WAVE":
        return "WAV"
    if head[4:8] == b"ftyp":
        return "MP4"  # also AAC in an MP4 (M4A) container
    if head.startswith(b"ID3") or (len(head) > 1 and head[0] == 0xFF and (head[1] & 0xE0) == 0xE0 and (head[1] & 0x06) != 0):
        return "MP3"
    if len(head) > 1 and head[0] == 0xFF and (head[1] & 0xF6) == 0xF0:  # AAC ADTS frame sync, layer 00
        return "AAC"
    text = head.lstrip(b"\xef\xbb\xbf \t\r\n").lower()
    if text.startswith((b"<?xml", b"<x3d", b"<!doctype x3d")):
        return "X3D"
    return None


def mismatch(filename: str, head: bytes) -> str | None:
    """Why the file's content doesn't match its name, or None when it does."""
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    want = EXT_FAMILY.get(ext)
    got = detect(head)
    if want is None or got == want or (want == "AAC" and got == "MP4"):
        return None
    return f"its name ends in .{ext}, but its content is {got or 'not a type the BMU accepts'}"

"""Private encrypted object storage with fail-closed resume validation.

Authorization belongs to the calling service. Object keys are opaque storage references,
never credentials; content is served through an authorized API proxy for revocation.
"""

import hashlib
import io
import re
import socket
import struct
import xml.etree.ElementTree as ET
import zipfile
from dataclasses import dataclass
from uuid import UUID, uuid4

import httpx
from app.core.errors import AppError
from app.core.security import decrypt, encrypt
from app.core.settings import get_settings

_OBJECT_KEY = re.compile(r"^[0-9a-f-]{36}/[0-9a-f-]{36}\.enc$")


@dataclass(frozen=True)
class StoredObject:
    object_key: str
    mime: str
    size: int
    sha256: str
    text: str | None = None


def _safe_key(key: str) -> str:
    if not _OBJECT_KEY.fullmatch(key):
        raise AppError(400, "INVALID_OBJECT", "Invalid private object reference")
    owner, item = key.split("/")
    try:
        UUID(owner)
        UUID(item.removesuffix(".enc"))
    except ValueError as exc:
        raise AppError(400, "INVALID_OBJECT", "Invalid private object reference") from exc
    return key


def _clamav_scan(content: bytes) -> None:
    settings = get_settings()
    if not settings.clamav_host:
        raise AppError(
            503, "SCANNER_UNAVAILABLE", "Binary document scanning is not configured; upload UTF-8 text"
        )
    try:
        with socket.create_connection((settings.clamav_host, settings.clamav_port), timeout=10) as scanner:
            scanner.sendall(b"zINSTREAM\0")
            for offset in range(0, len(content), 65536):
                chunk = content[offset : offset + 65536]
                scanner.sendall(struct.pack("!I", len(chunk)) + chunk)
            scanner.sendall(struct.pack("!I", 0))
            response = b""
            while len(response) < 4096 and b"\0" not in response:
                chunk = scanner.recv(1024)
                if not chunk:
                    break
                response += chunk
        if b"FOUND" in response:
            raise AppError(422, "UNSAFE_DOCUMENT", "The document did not pass the safety scan")
        if response.strip(b"\0\r\n ") != b"stream: OK":
            raise AppError(503, "SCANNER_UNAVAILABLE", "Document safety scanning is temporarily unavailable")
    except OSError as exc:
        raise AppError(
            503, "SCANNER_UNAVAILABLE", "Document safety scanning is temporarily unavailable"
        ) from exc


def validate_resume(content: bytes, mime: str) -> str | None:
    if not content or len(content) > get_settings().max_resume_bytes:
        raise AppError(413, "DOCUMENT_SIZE", "Upload a non-empty resume within the configured size limit")
    mime = mime.split(";", 1)[0].strip().lower()
    if mime == "text/plain":
        try:
            text = content.decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            raise AppError(422, "INVALID_DOCUMENT", "Text resumes must be valid UTF-8") from exc
        if any(ord(char) < 32 and char not in "\t\r\n" for char in text):
            raise AppError(422, "INVALID_DOCUMENT", "Text resumes cannot contain binary control characters")
        if "X5O!P%@AP[4" in text:
            raise AppError(422, "UNSAFE_DOCUMENT", "The document did not pass the safety scan")
        # Text remains untrusted data: no HTML rendering, tools, URL fetches, or instructions executed.
        return text
    if mime == "application/pdf":
        if not content.startswith(b"%PDF-") or b"%%EOF" not in content[-2048:]:
            raise AppError(422, "INVALID_DOCUMENT", "The upload is not a supported PDF")
        if re.search(rb"/(JavaScript|JS|Launch|OpenAction|AA|EmbeddedFile|XFA)\b", content, re.I):
            raise AppError(422, "UNSAFE_DOCUMENT", "Active PDF content is not accepted")
    elif mime == "application/vnd.openxmlformats-officedocument.wordprocessingml.document":
        try:
            with zipfile.ZipFile(io.BytesIO(content)) as document:
                entries = document.infolist()
                if len(entries) > 2000 or sum(item.file_size for item in entries) > 30_000_000:
                    raise AppError(422, "INVALID_DOCUMENT", "The document expands beyond the safe limit")
                if "word/document.xml" not in document.namelist():
                    raise AppError(422, "INVALID_DOCUMENT", "The upload is not a supported Word document")
                for item in entries:
                    if item.file_size > max(1, item.compress_size) * 100:
                        raise AppError(422, "INVALID_DOCUMENT", "The document expands beyond the safe limit")
                    if any(
                        marker in item.filename.lower()
                        for marker in ("vbaproject", "embeddings/", "activex/")
                    ):
                        raise AppError(422, "UNSAFE_DOCUMENT", "Active Word content is not accepted")
                    if item.filename.endswith(".rels"):
                        relationships = document.read(item)
                        # Match the isolated extractor's XML guard. UTF-16/32
                        # insert NULs into declarations and would otherwise
                        # bypass the byte pattern before the API parses XML.
                        if b"\0" in relationships or re.search(rb"<!DOCTYPE|<!ENTITY", relationships, re.I):
                            raise AppError(
                                422, "UNSAFE_DOCUMENT", "Document XML declarations are not accepted"
                            )
                        root = ET.fromstring(relationships)
                        if any(
                            node.attrib.get("TargetMode", "").lower() == "external" for node in root.iter()
                        ):
                            raise AppError(
                                422, "UNSAFE_DOCUMENT", "External document relationships are not accepted"
                            )
        except (zipfile.BadZipFile, RuntimeError, OSError, ET.ParseError) as exc:
            raise AppError(422, "INVALID_DOCUMENT", "The upload is not a supported Word document") from exc
    else:
        raise AppError(415, "DOCUMENT_TYPE", "Supported resumes are UTF-8 text, scanned PDF, or scanned DOCX")
    _clamav_scan(content)
    return None


def _storage_request(method: str, path: str, *, content: bytes | None = None) -> httpx.Response:
    settings = get_settings()
    secret = settings.supabase_service_role_key.get_secret_value()
    if not secret or not settings.supabase_url.startswith("https://"):
        raise AppError(503, "STORAGE_UNAVAILABLE", "Private storage is not configured")
    try:
        response = httpx.request(
            method,
            f"{settings.supabase_url.rstrip('/')}/storage/v1/{path}",
            content=content,
            headers={
                "Authorization": f"Bearer {secret}",
                "apikey": secret,
                "Content-Type": "application/octet-stream",
                "x-upsert": "false",
            },
            timeout=20,
            follow_redirects=False,
        )
    except httpx.HTTPError as exc:
        raise AppError(503, "STORAGE_UNAVAILABLE", "Private storage is temporarily unavailable") from exc
    if response.status_code == 404:
        raise AppError(404, "OBJECT_NOT_FOUND", "The private document is unavailable")
    if response.status_code >= 300:
        raise AppError(503, "STORAGE_UNAVAILABLE", "Private storage is temporarily unavailable")
    return response


def store_resume(content: bytes, mime: str, owner_id: UUID | str) -> StoredObject:
    text = validate_resume(content, mime)
    if text is None:
        from app.integrations.document_extract import extract_document_text

        text = extract_document_text(content, mime)
    object_key = f"{UUID(str(owner_id))}/{uuid4()}.enc"
    encrypted = encrypt(content).encode("ascii")
    settings = get_settings()
    if settings.storage_backend == "supabase":
        _storage_request("POST", f"object/{settings.storage_bucket}/{object_key}", content=encrypted)
    else:
        root = settings.local_storage_dir.resolve()
        destination = root / object_key
        destination.parent.mkdir(parents=True, exist_ok=True)
        with destination.open("xb") as output:
            output.write(encrypted)
    return StoredObject(object_key, mime, len(content), hashlib.sha256(content).hexdigest(), text)


def read_private(object_key: str) -> bytes:
    key = _safe_key(object_key)
    settings = get_settings()
    if settings.storage_backend == "supabase":
        encrypted = _storage_request("GET", f"object/authenticated/{settings.storage_bucket}/{key}").content
    else:
        try:
            encrypted = (settings.local_storage_dir.resolve() / key).read_bytes()
        except FileNotFoundError as exc:
            raise AppError(404, "OBJECT_NOT_FOUND", "The private document is unavailable") from exc
    return decrypt(encrypted.decode("ascii"))


def delete_private(object_key: str) -> None:
    key = _safe_key(object_key)
    settings = get_settings()
    if settings.storage_backend == "supabase":
        _storage_request("DELETE", f"object/{settings.storage_bucket}/{key}")
    else:
        (settings.local_storage_dir.resolve() / key).unlink(missing_ok=True)

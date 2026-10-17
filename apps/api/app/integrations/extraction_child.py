"""Minimal extraction subprocess: stdin bytes -> bounded JSON draft; no app imports."""

from __future__ import annotations

import io
import json
import logging
import re
import sys
import xml.etree.ElementTree as ET
import zipfile
from typing import Any


def _guards(cpu_seconds: int, memory_mb: int, output_bytes: int) -> None:
    if sys.platform != "win32":
        import resource

        resource.setrlimit(resource.RLIMIT_AS, (memory_mb * 1024 * 1024,) * 2)
        resource.setrlimit(resource.RLIMIT_CPU, (cpu_seconds, cpu_seconds + 1))
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
        resource.setrlimit(resource.RLIMIT_FSIZE, (output_bytes, output_bytes))

    def deny_external(event: str, args: tuple[Any, ...]) -> None:
        if event.startswith("socket.") or event in (
            "subprocess.Popen",
            "os.system",
            "os.posix_spawn",
            "os.exec",
            "os.fork",
        ):
            raise PermissionError("external operations disabled in document extractor")

    sys.addaudithook(deny_external)
    logging.disable(logging.CRITICAL)


def _xml(content: bytes) -> ET.Element:
    # Reject alternative encodings with NUL separators as well as DTD/entity
    # declarations. No XInclude expansion or relationship traversal occurs.
    if b"\0" in content or re.search(rb"<!DOCTYPE|<!ENTITY", content, re.I):
        raise ValueError("unsafe document XML")
    return ET.fromstring(content)


def _docx(content: bytes, uncompressed_limit: int, output_chars: int) -> str:
    with zipfile.ZipFile(io.BytesIO(content)) as archive:
        entries = archive.infolist()
        if len(entries) > 2000 or sum(item.file_size for item in entries) > uncompressed_limit:
            raise ValueError("document expansion limit")
        if sum(item.filename == "word/document.xml" for item in entries) != 1:
            raise ValueError("ambiguous document XML")
        for item in entries:
            if item.file_size > max(1, item.compress_size) * 100:
                raise ValueError("document compression limit")
            if any(marker in item.filename.lower() for marker in ("vbaproject", "embeddings/", "activex/")):
                raise ValueError("active document content")
            if item.filename.endswith(".rels"):
                with archive.open(item) as stream:
                    relation_bytes = stream.read(uncompressed_limit + 1)
                if len(relation_bytes) > uncompressed_limit:
                    raise ValueError("relationship expansion limit")
                root = _xml(relation_bytes)
                if any(node.attrib.get("TargetMode", "").lower() == "external" for node in root.iter()):
                    raise ValueError("external relationships disabled")
        with archive.open("word/document.xml") as stream:
            xml = stream.read(uncompressed_limit + 1)
        if len(xml) > uncompressed_limit:
            raise ValueError("document XML limit")
        root = _xml(xml)
        namespace = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
        pieces = []
        used = 0
        for paragraph in root.iter(namespace + "p"):
            line = "".join(
                (node.text or "")
                if node.tag == namespace + "t"
                else "\t"
                if node.tag == namespace + "tab"
                else "\n"
                if node.tag in (namespace + "br", namespace + "cr")
                else ""
                for node in paragraph.iter()
            )
            pieces.append(line[: output_chars - used])
            used += len(pieces[-1]) + 1
            if used >= output_chars:
                break
        return "\n".join(pieces)[:output_chars]


def _pdf(content: bytes, max_pages: int, uncompressed_limit: int, output_chars: int) -> str:
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(content), strict=True)
    if reader.is_encrypted or len(reader.pages) > max_pages:
        raise ValueError("encrypted or over-page-limit PDF")
    pieces = []
    expanded = used = 0
    for page in reader.pages:
        stream = page.get_contents()
        if stream is not None:
            expanded += len(stream.get_data())
            if expanded > uncompressed_limit:
                raise ValueError("PDF expanded stream limit")
        text = page.extract_text(extraction_mode="plain") or ""
        pieces.append(text[: output_chars - used])
        used += len(pieces[-1]) + 1
        if used >= output_chars:
            break
    reader.close()
    return "\n".join(pieces)[:output_chars]


def main() -> None:
    try:
        mime = sys.argv[1]
        input_bytes, max_pages, expanded, chars, cpu, memory, output_bytes = map(int, sys.argv[2:9])
        _guards(cpu, memory, output_bytes)
        # Trusted dependency directory supplied by the launcher, independent of
        # cwd/PYTHONPATH. Windows' venv redirector would otherwise spawn a second
        # process and conflict with the Job Object's one-process restriction.
        sys.path.insert(0, sys.argv[9])
        content = sys.stdin.buffer.read(input_bytes + 1)
        if len(content) > input_bytes:
            raise ValueError("input limit")
        if mime == "application/pdf":
            text = _pdf(content, max_pages, expanded, chars)
        elif mime == "application/vnd.openxmlformats-officedocument.wordprocessingml.document":
            text = _docx(content, expanded, chars)
        else:
            raise ValueError("unsupported document MIME")
        text = "".join(char for char in text if ord(char) >= 32 or char in "\n\r\t").strip()
        result = {"text": text or None}
    except Exception:
        result = {"text": None}  # Never serialize parser error strings or document bytes.
    encoded = json.dumps(result, ensure_ascii=True).encode("ascii")
    if len(encoded) <= 200_000:
        sys.stdout.buffer.write(encoded)


if __name__ == "__main__":
    main()

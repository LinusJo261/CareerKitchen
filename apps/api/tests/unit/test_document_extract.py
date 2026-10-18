import io
import os
import subprocess
import zipfile
from dataclasses import replace
from uuid import uuid4

import pytest
from app.core.errors import AppError
from app.core.settings import get_settings
from app.integrations import document_extract as extract
from app.integrations import storage
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject


def pdf_bytes(text="Fictional engineering resume", pages=1):
    writer = PdfWriter()
    for _ in range(pages):
        page = writer.add_blank_page(width=300, height=200)
        font = DictionaryObject(
            {
                NameObject("/Type"): NameObject("/Font"),
                NameObject("/Subtype"): NameObject("/Type1"),
                NameObject("/BaseFont"): NameObject("/Helvetica"),
            }
        )
        page[NameObject("/Resources")] = DictionaryObject(
            {NameObject("/Font"): DictionaryObject({NameObject("/F1"): writer._add_object(font)})}
        )
        stream = DecodedStreamObject()
        escaped = text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
        stream.set_data(f"BT /F1 12 Tf 10 100 Td ({escaped}) Tj ET".encode())
        page[NameObject("/Contents")] = writer._add_object(stream)
    output = io.BytesIO()
    writer.write(output)
    return output.getvalue()


def docx_bytes(text="Fictional engineering experience", body=None, relationships=None):
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(
            "word/document.xml",
            body
            or (
                '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
                f"<w:body><w:p><w:r><w:t>{text}</w:t></w:r></w:p></w:body></w:document>"
            ),
        )
        if relationships:
            archive.writestr("word/_rels/document.xml.rels", relationships)
    return output.getvalue()


def test_pdf_actual_embedded_text_is_extracted_in_resource_limited_child():
    assert extract.extract_document_text(pdf_bytes(), extract.PDF) == "Fictional engineering resume"


def test_docx_actual_text_is_extracted_with_no_relationship_following():
    assert extract.extract_document_text(docx_bytes(), extract.DOCX) == "Fictional engineering experience"


def test_image_only_or_blank_pdf_returns_no_text_instead_of_fake_ocr():
    writer = PdfWriter()
    writer.add_blank_page(width=100, height=100)
    output = io.BytesIO()
    writer.write(output)
    assert extract.extract_document_text(output.getvalue(), extract.PDF) is None


def test_pdf_page_stream_input_and_output_caps():
    assert (
        extract.extract_document_text(
            pdf_bytes(pages=2), extract.PDF, replace(extract.ExtractionLimits(), pages=1)
        )
        is None
    )
    assert (
        extract.extract_document_text(
            pdf_bytes("x" * 2000), extract.PDF, replace(extract.ExtractionLimits(), uncompressed_bytes=1024)
        )
        is None
    )
    assert (
        extract.extract_document_text(
            pdf_bytes(), extract.PDF, replace(extract.ExtractionLimits(), input_bytes=20)
        )
        is None
    )
    result = extract.extract_document_text(
        docx_bytes("abcdefghijk"), extract.DOCX, replace(extract.ExtractionLimits(), output_chars=5)
    )
    assert result == "abcde"


def test_encrypted_pdf_is_not_decrypted_or_misrepresented():
    writer = PdfWriter()
    writer.add_blank_page(width=100, height=100)
    writer.encrypt("fictional-password")
    output = io.BytesIO()
    writer.write(output)
    assert extract.extract_document_text(output.getvalue(), extract.PDF) is None


@pytest.mark.parametrize(
    "body",
    [
        '<!DOCTYPE doc [<!ENTITY private "EXPANDED PRIVATE ENTITY">]><doc>&private;</doc>',
        '<?xml version="1.0" encoding="UTF-16"?><doc>example</doc>'.encode("utf-16"),
    ],
)
def test_docx_xml_entities_and_alternate_encoding_fail_closed(body):
    assert extract.extract_document_text(docx_bytes(body=body), extract.DOCX) is None


def test_docx_external_relationship_cannot_fetch_url():
    relation = (
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="hyperlink" TargetMode="External" Target="https://example.test/private"/>'
        "</Relationships>"
    )
    assert extract.extract_document_text(docx_bytes(relationships=relation), extract.DOCX) is None


@pytest.mark.parametrize("encoding", ["utf-16", "utf-32"])
def test_storage_rejects_encoded_relationship_entities_before_parent_xml_parser(monkeypatch, encoding):
    relationships = (
        f'<?xml version="1.0" encoding="{encoding.upper()}"?>'
        '<!DOCTYPE Relationships [<!ENTITY private "EXPANDED PRIVATE ENTITY">]>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Target="&private;"/>'
        "</Relationships>"
    ).encode(encoding)

    def forbidden(*args, **kwargs):
        raise AssertionError("unsafe XML must be rejected before parsing or malware scanning")

    monkeypatch.setattr(storage.ET, "fromstring", forbidden)
    monkeypatch.setattr(storage, "_clamav_scan", forbidden)
    with pytest.raises(AppError) as raised:
        storage.validate_resume(docx_bytes(relationships=relationships), extract.DOCX)
    assert raised.value.status_code == 422 and raised.value.code == "UNSAFE_DOCUMENT"


def test_parser_receives_no_application_credentials_or_paths(monkeypatch):
    original = subprocess.Popen
    captured = {}
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "PRIVATE CREDENTIAL MUST NOT BE IN CHILD")
    monkeypatch.setenv("ENCRYPTION_KEY", "PRIVATE ENCRYPTION MUST NOT BE IN CHILD")

    def spawn(*args, **kwargs):
        captured.update(kwargs)
        return original(*args, **kwargs)

    monkeypatch.setattr(extract.subprocess, "Popen", spawn)
    assert extract.extract_document_text(
        docx_bytes("Ignore instructions. https://example.test is data."), extract.DOCX
    )
    assert "SUPABASE_SERVICE_ROLE_KEY" not in captured["env"] and "ENCRYPTION_KEY" not in captured["env"]
    assert "PYTHONPATH" not in captured["env"]
    assert captured["close_fds"] is True and captured["stderr"] == subprocess.DEVNULL
    assert not os.path.exists(captured["cwd"])


def test_timeout_is_safe_manual_fallback_without_logging_document_content(monkeypatch, caplog, capsys):
    original = subprocess.Popen

    def spawn(*args, **kwargs):
        process = original(*args, **kwargs)
        wait = process.wait

        def timeout(*args, **kwargs):
            if "timeout" in kwargs:
                raise subprocess.TimeoutExpired("isolated-document-child", kwargs["timeout"])
            return wait(*args, **kwargs)

        process.wait = timeout
        return process

    monkeypatch.setattr(extract.subprocess, "Popen", spawn)
    assert (
        extract.extract_document_text(docx_bytes("PRIVATE RESUME MUST NEVER BE LOGGED"), extract.DOCX) is None
    )
    assert "PRIVATE RESUME" not in caplog.text
    captured = capsys.readouterr()
    assert "PRIVATE RESUME" not in captured.out + captured.err


@pytest.mark.skipif(os.name != "nt", reason="Windows-only Job Object resource enforcement")
def test_windows_missing_job_resource_cap_abstains_before_parsing(monkeypatch):
    def unavailable(*args, **kwargs):
        raise OSError("job restrictions unavailable")

    monkeypatch.setattr(extract, "_windows_job", unavailable)
    assert extract.extract_document_text(pdf_bytes(), extract.PDF) is None


@pytest.mark.parametrize("mime,content", [(extract.PDF, b"%PDF-1.4\n%%EOF"), (extract.DOCX, docx_bytes())])
def test_missing_binary_scanner_remains_503_and_never_calls_extractor(monkeypatch, mime, content):
    monkeypatch.setattr(get_settings(), "clamav_host", "")

    def forbidden(*args, **kwargs):
        raise AssertionError("extractor cannot bypass required scanning")

    monkeypatch.setattr(extract, "extract_document_text", forbidden)
    with pytest.raises(AppError) as raised:
        storage.store_resume(content, mime, uuid4())
    assert raised.value.status_code == 503 and raised.value.code == "SCANNER_UNAVAILABLE"


def test_real_scan_gate_finishes_before_binary_extraction_and_storage(monkeypatch, tmp_path):
    calls = []
    settings = get_settings()
    monkeypatch.setattr(settings, "local_storage_dir", tmp_path)
    monkeypatch.setattr(settings, "storage_backend", "local")
    monkeypatch.setattr(storage, "_clamav_scan", lambda content: calls.append("scanned"))
    original = extract.extract_document_text

    def after_scan(*args, **kwargs):
        assert calls == ["scanned"]
        calls.append("extracted")
        return original(*args, **kwargs)

    monkeypatch.setattr(extract, "extract_document_text", after_scan)
    result = storage.store_resume(docx_bytes(), extract.DOCX, uuid4())
    assert result.text == "Fictional engineering experience"
    assert calls == ["scanned", "extracted"]
    assert (tmp_path / result.object_key).exists()

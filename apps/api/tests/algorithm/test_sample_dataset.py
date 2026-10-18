"""Synthetic source import boundaries; fixtures describe no real applicant."""

from copy import deepcopy

import httpx
import pytest

from scripts import sample_dataset as source

RESUME = {
    "resume_id": "R_000000",
    "role": "Software Engineer",
    "seniority": "Senior",
    "years_experience": 12,
    "industry": "EdTech",
    "education": "BSc",
    "skills": ["Python", "Git"],
    "summary": "Synthetic Software Engineer with 12 years of experience.",
    "experience_bullets": ["Maintained fictional development workflows"],
}
JOB = {
    "job_id": "J_000000",
    "job_title": "Software Engineer",
    "seniority": "Senior",
    "industry": "EdTech",
    "must_have_skills": ["Python"],
    "nice_to_have_skills": ["Git"],
    "description": "Synthetic engineering vacancy for development.",
    "responsibilities": ["Maintain fictional software"],
    "requirements": ["Relevant synthetic experience"],
}


@pytest.fixture
def frozen(tmp_path, monkeypatch):
    """Small pinned immutable corpus; exercise network and disk through the public API."""
    raw_files = {
        "README.md": b"---\nlicense: mit\n---\nSynthetic fixture\n",
        "resumes.parquet": b"pinned synthetic resume parquet fixture",
        "jobs.parquet": b"pinned synthetic jobs parquet fixture",
    }
    source_files = {
        filename: {**source.SOURCE_FILES[filename], "bytes": len(raw), "sha256": source.sha256(raw)}
        for filename, raw in raw_files.items()
    }
    tables = {"resumes": [deepcopy(RESUME)], "jobs": [deepcopy(JOB)]}
    table_files = {}
    for name, rows in tables.items():
        raw = b"".join(source.canonical_bytes(row) for row in rows)
        table_files[name] = {
            "file": name + ".jsonl",
            "count": len(rows),
            "bytes": len(raw),
            "sha256": source.sha256(raw),
        }
    monkeypatch.setattr(source, "COUNTS", {name: len(rows) for name, rows in tables.items()})
    monkeypatch.setattr(source, "SOURCE_FILES", source_files)
    monkeypatch.setattr(source, "TABLE_FILES", table_files)
    urls = []

    def fetch(url, maximum):
        urls.append(url)
        selected = [
            name for name, meta in source_files.items() if url == source.BASE_URL + meta["source_path"]
        ]
        assert len(selected) == 1, "Attempted download outside the approved source inventory"
        raw = raw_files[selected[0]]
        assert len(raw) <= maximum
        return raw

    monkeypatch.setattr(source, "_fetch", fetch)
    monkeypatch.setattr(source, "_parquet_rows", lambda raw, name: deepcopy(tables[name]))
    directory = tmp_path / "sample"
    provenance = source.download_source(directory)
    return directory, tables, provenance, urls


def test_only_synthetic_jobs_applicants_and_license_card_are_downloaded(frozen):
    directory, expected, provenance, urls = frozen
    tables, checked = source.load_source(directory)
    assert tables == expected
    assert checked == provenance
    assert len(urls) == 3
    assert all(source.REVISION in url for url in urls)
    assert not any("matches/" in url or "embeddings/" in url for url in urls)
    assert checked["fictional"] is True
    assert checked["license"] == "MIT"
    assert checked["manifest_sha256"] == source.sha256((directory / "manifest.json").read_bytes())


def test_existing_source_is_verified_offline_and_idempotent(frozen, monkeypatch):
    directory, _, provenance, _ = frozen

    def forbidden(*args, **kwargs):
        pytest.fail("Offline verification attempted network access or optional Parquet decoding")

    monkeypatch.setattr(source, "_fetch", forbidden)
    monkeypatch.setattr(source, "_parquet_rows", forbidden)
    assert source.download_source(directory) == provenance
    assert source.load_source(directory / "manifest.json")[1] == provenance


@pytest.mark.parametrize(
    "filename", ["README.md", "resumes.parquet", "jobs.parquet", "resumes.jsonl", "jobs.jsonl"]
)
def test_tampered_source_and_derived_files_are_rejected(frozen, filename):
    directory, _, _, _ = frozen
    path = directory / filename
    raw = path.read_bytes()
    path.write_bytes(bytes([raw[0] ^ 1]) + raw[1:])
    with pytest.raises(ValueError, match="SHA256"):
        source.load_source(directory)


@pytest.mark.parametrize(
    "change",
    [
        {"revision": "main"},
        {"license": "unknown"},
        {"fictional": False},
        {"dataset": "Aunsiels/JTH"},
        {"schema_version": True},
        {"source_files": {}},
        {"tables": {"matches": {}}},
    ],
)
def test_manifest_cannot_substitute_sources_or_labels(frozen, change):
    directory, _, provenance, _ = frozen
    manifest = {key: value for key, value in provenance.items() if key != "manifest_sha256"}
    manifest.update(change)
    (directory / "manifest.json").write_bytes(source.canonical_bytes(manifest))
    with pytest.raises(ValueError, match="manifest"):
        source.load_source(directory)


def test_forged_derived_data_and_recomputed_manifest_checksum_still_fail(frozen):
    directory, _, provenance, _ = frozen
    manifest = deepcopy(provenance)
    changed = {**RESUME, "role": "Injected role"}
    raw = source.canonical_bytes(changed)
    (directory / "resumes.jsonl").write_bytes(raw)
    manifest["tables"]["resumes"].update(bytes=len(raw), sha256=source.sha256(raw))
    (directory / "manifest.json").write_bytes(source.canonical_bytes(manifest))
    with pytest.raises(ValueError, match="manifest"):
        source.load_source(directory)


@pytest.mark.parametrize(
    "field,value",
    [
        ("resume_id", "someone@example.com"),
        ("seniority", []),
        ("years_experience", True),
        ("years_experience", -1),
        ("years_experience", 61),
        ("summary", "x" * 20_001),
        ("summary", "\x00text"),
        ("skills", ["Python", "python"]),
        ("skills", []),
        ("skills", ["x"] * 31),
        ("experience_bullets", "unstructured"),
    ],
)
def test_applicant_source_fields_are_strict_and_bounded(field, value):
    with pytest.raises(ValueError):
        source.validate_resume({**RESUME, field: value})


@pytest.mark.parametrize(
    "field,value",
    [
        ("job_id", "J_0"),
        ("description", ""),
        ("must_have_skills", []),
        ("nice_to_have_skills", ["Git", "git"]),
        ("responsibilities", [None]),
    ],
)
def test_vacancy_source_fields_are_strict_and_bounded(field, value):
    with pytest.raises(ValueError):
        source.validate_job({**JOB, field: value})


def test_source_schema_rejects_outcomes_and_implicit_missing_fields():
    with pytest.raises(ValueError, match="schema"):
        source.validate_resume({**RESUME, "hired": True})
    missing = {key: value for key, value in JOB.items() if key != "seniority"}
    with pytest.raises(ValueError, match="schema"):
        source.validate_job(missing)
    with pytest.raises(ValueError, match="Only synthetic"):
        source.validate_tables({"resumes": [], "jobs": [], "matches": []})


def test_full_pinned_counts_and_unique_ids_are_required(monkeypatch):
    with pytest.raises(ValueError, match="10000"):
        source.validate_tables({"resumes": [RESUME], "jobs": [JOB]})
    monkeypatch.setattr(source, "COUNTS", {"resumes": 2, "jobs": 1})
    with pytest.raises(ValueError, match="Duplicate"):
        source.validate_tables({"resumes": [RESUME, RESUME], "jobs": [JOB]})


def test_partial_download_directory_is_never_overwritten(tmp_path):
    marker = tmp_path / "README.md"
    marker.write_text("existing data")
    with pytest.raises(ValueError, match="empty"):
        source.download_source(tmp_path)
    assert marker.read_text() == "existing data"


def test_oversized_manifest_is_refused_before_json_parsing(tmp_path):
    (tmp_path / "manifest.json").write_bytes(b" " * (source.MAX_MANIFEST_BYTES + 1))
    with pytest.raises(ValueError, match="oversized"):
        source.load_source(tmp_path)


def _mock_network(monkeypatch, handler):
    original = httpx.Client
    transport = httpx.MockTransport(handler)
    monkeypatch.setattr(httpx, "Client", lambda **kwargs: original(transport=transport, **kwargs))


def test_fetch_checks_redirect_origin_before_issuing_request(monkeypatch):
    seen = []

    def handler(request):
        seen.append(str(request.url))
        return httpx.Response(302, headers={"location": "http://127.0.0.1/private"})

    _mock_network(monkeypatch, handler)
    with pytest.raises(ValueError, match="outside official"):
        source._fetch(source.BASE_URL + "README.md", 100)
    assert seen == [source.BASE_URL + "README.md"]


def test_fetch_bounds_download_and_redirects(monkeypatch):
    _mock_network(monkeypatch, lambda request: httpx.Response(200, content=b"123456"))
    with pytest.raises(ValueError, match="download size"):
        source._fetch(source.BASE_URL + "README.md", 5)


@pytest.mark.parametrize(
    "url",
    [
        "https://huggingface.co.attacker.test/data",
        "https://user:secret@huggingface.co/data",
        "http://huggingface.co/data",
        "https://huggingface.co:444/data",
        "https://localhost/data",
    ],
)
def test_fetch_never_sends_requests_to_unapproved_origins(monkeypatch, url):
    _mock_network(monkeypatch, lambda request: pytest.fail("Unapproved source received a request"))
    with pytest.raises(ValueError, match="outside official"):
        source._fetch(url, 100)

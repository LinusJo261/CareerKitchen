from types import SimpleNamespace

import pytest

from scripts import check_secrets


def scan_source(tmp_path, monkeypatch, content):
    monkeypatch.chdir(tmp_path)
    path = tmp_path / "configuration.py"
    path.write_text(content, encoding="utf-8")

    def git_files(command, **kwargs):
        assert command == ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"]
        assert kwargs == {"capture_output": True, "check": True}
        return SimpleNamespace(stdout=b"configuration.py\0")

    monkeypatch.setattr(check_secrets.subprocess, "run", git_files)
    return check_secrets.main()


@pytest.mark.parametrize("last_character", ["A", "-", "_"])
def test_google_api_key_is_rejected_without_printing_its_value(tmp_path, monkeypatch, capsys, last_character):
    # Construct the fictional key so the test source cannot trigger the scanner.
    key = "AI" + "za" + "b7" * 17 + last_character
    assert scan_source(tmp_path, monkeypatch, f"GEMINI_API_KEY = '{key}'\n") == 1
    output = capsys.readouterr().out
    assert "configuration.py" in output
    assert key not in output


@pytest.mark.parametrize(
    "content",
    [
        "GEMINI_API_KEY = ''\n",
        "GEMINI_API_KEY = 'REPLACE_SERVER_ONLY_SECRET'\n",
        "PREFIX = 'AI' + 'za'\n",
    ],
)
def test_empty_keys_and_documentation_placeholders_are_allowed(tmp_path, monkeypatch, content):
    assert scan_source(tmp_path, monkeypatch, content) == 0


def test_incomplete_google_api_key_is_not_reported(tmp_path, monkeypatch):
    key = "AI" + "za" + "b" * 34
    assert scan_source(tmp_path, monkeypatch, f"INCOMPLETE_EXAMPLE = '{key}'\n") == 0

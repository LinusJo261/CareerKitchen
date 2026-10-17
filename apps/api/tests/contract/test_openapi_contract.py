import json
from pathlib import Path

from app.main import create_app
from fastapi.routing import APIRoute

ROOT = Path(__file__).resolve().parents[4]
METHODS = {"get", "post", "put", "patch", "delete"}


def test_checked_in_openapi_matches_runtime_contract():
    application = create_app()
    try:
        assert json.loads((ROOT / "docs/openapi.json").read_text(encoding="utf-8")) == application.openapi()
    finally:
        application.state.engine.dispose()


def test_all_business_operations_document_bearer_and_mutation_idempotency():
    application = create_app()
    try:
        for path, methods in application.openapi()["paths"].items():
            if path in {"/v1/health", "/v1/ready"}:
                continue
            for method, operation in methods.items():
                if method not in METHODS:
                    continue
                assert operation["security"] == [{"SupabaseBearer": []}], (path, method)
                if method != "get":
                    keys = [item for item in operation["parameters"] if item["name"] == "Idempotency-Key"]
                    assert len(keys) == 1 and keys[0]["required"], (path, method)
                assert "422" in operation["responses"], (path, method)
    finally:
        application.state.engine.dispose()


def test_every_success_response_has_a_concrete_schema_and_downloads_are_binary():
    application = create_app()
    try:
        for path, methods in application.openapi()["paths"].items():
            for method, operation in methods.items():
                if method not in METHODS:
                    continue
                for code, response in operation["responses"].items():
                    if not code.startswith("2"):
                        continue
                    for mime, definition in response.get("content", {}).items():
                        assert definition.get("schema"), (path, method, mime)
                        if mime == "application/octet-stream":
                            assert definition["schema"] == {"type": "string", "format": "binary"}
        for route in application.routes:
            if isinstance(route, APIRoute) and route.path.startswith("/v1"):
                if route.path.endswith("/shortlist/approve"):
                    assert not any(
                        code.startswith("2")
                        for code in application.openapi()["paths"][route.path]["post"]["responses"]
                    )
    finally:
        application.state.engine.dispose()

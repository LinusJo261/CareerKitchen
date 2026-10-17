"""Export the running FastAPI contract deterministically, without connecting to services."""

import argparse
import json
from pathlib import Path

from app.main import create_app

ROOT = Path(__file__).resolve().parents[1]
INVENTORY_MARKER = "<!-- BEGIN GENERATED ENDPOINT INVENTORY -->"


def schema_name(schema: dict) -> str:
    if "$ref" in schema:
        return schema["$ref"].rsplit("/", 1)[-1]
    if schema.get("format") == "binary":
        return "binary attachment"
    return schema.get("type", "—")


def endpoint_inventory(schema: dict) -> str:
    rows = ["| Method | Path | Request schema | Success schema |", "|---|---|---|---|"]
    count = 0
    for path, methods in sorted(schema["paths"].items()):
        for method, operation in sorted(methods.items()):
            if method not in {"get", "post", "put", "patch", "delete"}:
                continue
            count += 1
            content = operation.get("requestBody", {}).get("content", {})
            request = ", ".join(schema_name(item.get("schema", {})) for item in content.values()) or "—"
            responses = []
            for code, response in operation["responses"].items():
                if str(code).startswith("2"):
                    names = [
                        schema_name(item.get("schema", {})) for item in response.get("content", {}).values()
                    ]
                    responses.append(f"{code}: " + (", ".join(names) or "empty"))
            success = "; ".join(responses) or "disabled (409)"
            rows.append(f"| {method.upper()} | `{path}` | {request} | {success} |")
    return f"\n\n{count} operations across {len(schema['paths'])} paths.\n\n" + "\n".join(rows) + "\n"


def exported_schema() -> dict:
    application = create_app()
    try:
        return application.openapi()
    finally:
        application.state.engine.dispose()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Fail if the checked-in schema differs")
    parser.add_argument("--output", type=Path, default=ROOT / "docs/openapi.json")
    args = parser.parse_args()
    schema = exported_schema()
    expected = json.dumps(schema, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    reference = ROOT / "docs/api.md"
    reference_text = reference.read_text(encoding="utf-8") if reference.exists() else ""
    expected_reference = (
        reference_text.split(INVENTORY_MARKER)[0] + INVENTORY_MARKER + endpoint_inventory(schema)
    )
    if args.check:
        if not args.output.exists() or args.output.read_text(encoding="utf-8") != expected:
            print(
                "OpenAPI changed. Run python scripts/export_openapi.py and regenerate the TypeScript client."
            )
            return 1
        if args.output == ROOT / "docs/openapi.json" and reference_text != expected_reference:
            print("API endpoint inventory changed. Run python scripts/export_openapi.py.")
            return 1
        print("OpenAPI export matches the running application")
        return 0
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(expected, encoding="utf-8", newline="\n")
    if args.output == ROOT / "docs/openapi.json":
        reference.write_text(expected_reference, encoding="utf-8", newline="\n")
    print(f"Exported {len(schema['paths'])} API paths to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

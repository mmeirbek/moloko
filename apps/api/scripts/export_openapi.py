"""Write the API's OpenAPI schema to packages/shared-types/openapi.json.

The frontend's TypeScript types are generated from that file
(``npm run generate -w @moloko/shared-types``). CI fails if it is out of date.

    uv run python scripts/export_openapi.py [--check]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
TARGET = ROOT / "packages" / "shared-types" / "openapi.json"


def render() -> str:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from app.core.config import Settings
    from app.main import create_app

    # Placeholder settings: building the schema opens no connections.
    settings = Settings(
        _env_file=None,
        database_url="postgresql+asyncpg://schema:schema@localhost/schema",
        redis_url="redis://localhost:6379/0",
        secret_key="schema-export-" + "0" * 32,
        log_level="WARNING",
    )
    schema = create_app(settings).openapi()
    return json.dumps(schema, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true", help="Fail if the file is stale")
    args = parser.parse_args()
    content = render()
    if args.check:
        current = TARGET.read_text(encoding="utf-8") if TARGET.exists() else ""
        if current != content:
            sys.exit(f"{TARGET.relative_to(ROOT)} is stale: run scripts/export_openapi.py")
        print("OpenAPI schema is up to date.")
        return
    TARGET.parent.mkdir(parents=True, exist_ok=True)
    TARGET.write_text(content, encoding="utf-8")
    print(f"Wrote {TARGET.relative_to(ROOT)}")


if __name__ == "__main__":
    main()

"""Dump the FastAPI OpenAPI spec to apps/web/openapi.json for TS codegen.

Standalone build tool (not request-serving): `make types` runs this offline
via app.openapi() — no running server needed — then openapi-typescript turns
the dumped spec into apps/web/lib/openapi.ts. The dumped openapi.json is a
gitignored intermediate; only the generated .ts is committed.
"""

import json
from pathlib import Path

from apps.api.main import app

OUT = Path(__file__).resolve().parents[3] / "apps" / "web" / "openapi.json"


def main() -> None:
    OUT.write_text(json.dumps(app.openapi(), indent=2) + "\n")
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()

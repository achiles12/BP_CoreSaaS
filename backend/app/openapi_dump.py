"""Print the OpenAPI schema as JSON without starting the server (B08 D15).

Used by `make gen-client` / `make gen-client-check` and CI. Importing the app
does not touch Postgres or Redis (connections open in the lifespan), so this
works offline. Fails (exit 1) if two routes share an operationId, because the
generated frontend hooks are named after it.

Usage: python -m app.openapi_dump [output-file]   (stdout when omitted)
"""

import json
import sys
from collections import Counter

from app.main import create_app


def build_schema() -> dict:
    """Return the app's OpenAPI schema; raise ValueError on duplicate operationIds."""
    schema = create_app().openapi()
    ids = [op["operationId"] for path in schema["paths"].values() for op in path.values()]
    dupes = sorted(k for k, n in Counter(ids).items() if n > 1)
    if dupes:
        raise ValueError(f"duplicate operationIds: {', '.join(dupes)}")
    return schema


def main(argv: list[str]) -> int:
    try:
        schema = build_schema()
    except ValueError as exc:
        print(f"openapi_dump: {exc}", file=sys.stderr)
        return 1
    # sort_keys + trailing newline: stable output, so the drift check diff is clean.
    text = json.dumps(schema, indent=2, sort_keys=True) + "\n"
    if len(argv) > 1:
        with open(argv[1], "w", encoding="utf-8") as fh:
            fh.write(text)
    else:
        sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))

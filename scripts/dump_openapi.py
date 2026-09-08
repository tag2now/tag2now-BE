"""Write the OpenAPI schema tag2now-FE checks itself against.

Run this whenever a route, a request model or a response model changes, and
commit the result -- test_openapi_contract fails until you do.

Importing app requires the settings a running server needs, so this expects an
env/.env.<profile> file. There is one on any machine that can run the server.
"""

import json
from pathlib import Path

from app import app

OUTPUT = Path(__file__).resolve().parent.parent / "openapi.json"


def main() -> None:
    # sort_keys because the diff is the point: an incidental reordering that
    # says nothing about the contract would bury the change that does.
    OUTPUT.write_text(json.dumps(app.openapi(), indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"wrote {OUTPUT}")


if __name__ == "__main__":
    main()

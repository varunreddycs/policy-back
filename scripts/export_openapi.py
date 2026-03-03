from __future__ import annotations

import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
	sys.path.insert(0, str(ROOT))

from app import app  # noqa: E402


def main() -> None:
	schema = app.openapi()
	out_path = ROOT / "openapi.json"
	out_path.write_text(json.dumps(schema, ensure_ascii=False, indent=2), encoding="utf-8")
	print(f"Wrote {out_path}")


if __name__ == "__main__":
	main()

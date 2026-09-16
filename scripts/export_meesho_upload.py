"""CLI: export the catalogue in the exact shape it was downloaded from
Meesho (same columns, order, and sheet name as data/raw/*.xls's "Meesho"
sheet) -- for re-uploading to Meesho's bulk tool, not for human review
(see scripts/export_catalogue.py for that).

Every seller_sku appears. Only APPROVED (effective status) rows get the
generated title/description/keywords; everything else keeps its original
Meesho content untouched, so this is safe to re-upload as an incremental
update.

Usage:
    python scripts/export_meesho_upload.py [--output path.xlsx]
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.database.db import DEFAULT_DATABASE_URL, get_db
from app.export.meesho_upload_export import export_meesho_upload

DEFAULT_OUTPUT = (
    Path(__file__).resolve().parent.parent / "data" / "processed" / "santerra_meesho_upload.xlsx"
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--database-url", default=os.environ.get("DATABASE_URL", DEFAULT_DATABASE_URL))
    args = parser.parse_args()

    with get_db(args.database_url) as conn:
        n = export_meesho_upload(conn, args.output)

    print(f"Wrote {n} rows to {args.output}")


if __name__ == "__main__":
    main()

"""CLI: export the optimized catalogue (original vs. generated listing
fields, scores, approval status) for human review before Meesho upload.

Usage:
    python scripts/export_catalogue.py [--status APPROVED] [--output path.xlsx]
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.database.db import DEFAULT_DATABASE_URL, get_db
from app.export.catalogue_export import export_catalogue

DEFAULT_OUTPUT = (
    Path(__file__).resolve().parent.parent
    / "data"
    / "processed"
    / "santerra_optimized_catalogue.xlsx"
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--status",
        choices=["APPROVED", "NEEDS_REVIEW", "REJECTED"],
        default=None,
        help="filter to one effective status (human decision, else the pipeline's own "
        "verdict); default includes all so a human can review everything",
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--database-url", default=os.environ.get("DATABASE_URL", DEFAULT_DATABASE_URL))
    args = parser.parse_args()

    with get_db(args.database_url) as conn:
        n = export_catalogue(conn, args.output, effective_status=args.status)

    print(f"Wrote {n} rows to {args.output}")


if __name__ == "__main__":
    main()

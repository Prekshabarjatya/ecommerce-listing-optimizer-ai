"""CLI: parse Santerra catalogue workbooks and upsert them into the
product-master Postgres database.

Usage:
    python scripts/load_database.py path/to/file1.xlsx path/to/file2.xls
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.database.db import DEFAULT_DATABASE_URL, get_db
from app.database.repository import (
    count_inventory_items,
    count_listings,
    upsert_inventory_records,
    upsert_listing_records,
)
from app.ingestion.cleaner import clean_sheet
from app.ingestion.excel_parser import parse_workbook
from app.ingestion.product_master import build_inventory_master, build_listing_master
from app.ingestion.schema_map import SourceType


def run(input_paths: list[Path], database_url: str) -> None:
    with get_db(database_url) as conn:
        for path in input_paths:
            print(f"Parsing {path.name} ...")
            sheets = parse_workbook(path)
            if not sheets:
                print(f"  no recognized sheets in {path.name}, skipping")
                continue

            for source_type, raw_df in sheets.items():
                cleaned = clean_sheet(raw_df, source_type)
                if source_type is SourceType.INVENTORY_UPDATE:
                    result = build_inventory_master(cleaned)
                    n = upsert_inventory_records(conn, result.records)
                    print(f"  upserted {n} inventory_items rows")
                else:
                    result = build_listing_master(cleaned)
                    n = upsert_listing_records(conn, result.records)
                    print(f"  upserted {n} meesho_listings rows")

                for err in result.row_errors[:5]:
                    print(f"    ! {err}")

        print(
            f"Database now has {count_inventory_items(conn)} inventory_items, "
            f"{count_listings(conn)} meesho_listings"
        )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("inputs", nargs="+", type=Path, help="workbook paths")
    parser.add_argument("--database-url", default=os.environ.get("DATABASE_URL", DEFAULT_DATABASE_URL))
    args = parser.parse_args()
    run(args.inputs, args.database_url)


if __name__ == "__main__":
    main()

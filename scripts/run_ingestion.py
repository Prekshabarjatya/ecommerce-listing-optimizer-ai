"""CLI: parse one or more Santerra catalogue workbooks into cleaned,
validated product masters under data/processed/.

Usage:
    python scripts/run_ingestion.py path/to/file1.xlsx path/to/file2.xls ...
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.ingestion.cleaner import clean_sheet
from app.ingestion.excel_parser import parse_workbook
from app.ingestion.product_master import (
    IngestionResult,
    build_inventory_master,
    build_listing_master,
)
from app.ingestion.schema_map import SourceType

BUILDERS = {
    SourceType.INVENTORY_UPDATE: build_inventory_master,
    SourceType.MEESHO_LISTING: build_listing_master,
}

OUTPUT_FILENAMES = {
    SourceType.INVENTORY_UPDATE: "inventory_master.csv",
    SourceType.MEESHO_LISTING: "listing_master.csv",
}


def run(input_paths: list[Path], output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    collected: dict[SourceType, list] = {}
    total_result: dict[SourceType, IngestionResult] = {}

    for path in input_paths:
        print(f"Parsing {path.name} ...")
        sheets = parse_workbook(path)
        if not sheets:
            print(f"  no recognized sheets in {path.name}, skipping")
            continue

        for source_type, raw_df in sheets.items():
            cleaned = clean_sheet(raw_df, source_type)
            result = BUILDERS[source_type](cleaned)
            print(
                f"  {source_type.value}: {len(result.records)} records, "
                f"{len(result.row_errors)} row errors, "
                f"{result.duplicate_keys_dropped} duplicates dropped"
            )
            for err in result.row_errors[:5]:
                print(f"    ! {err}")
            collected.setdefault(source_type, []).extend(result.records)

    for source_type, records in collected.items():
        if not records:
            continue
        out_path = output_dir / OUTPUT_FILENAMES[source_type]
        df = pd.DataFrame([r.model_dump() for r in records])
        df.to_csv(out_path, index=False)
        print(f"Wrote {len(df)} rows to {out_path}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("inputs", nargs="+", type=Path, help="workbook paths")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path(__file__).resolve().parent.parent / "data" / "processed",
    )
    args = parser.parse_args()
    run(args.inputs, args.output_dir)


if __name__ == "__main__":
    main()

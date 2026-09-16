from pathlib import Path

from app.ingestion.cleaner import clean_sheet
from app.ingestion.excel_parser import parse_workbook
from app.ingestion.product_master import build_inventory_master, build_listing_master
from app.ingestion.schema_map import SourceType

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"


def test_inventory_update_drops_instruction_row_and_parses_data():
    sheets = parse_workbook(FIXTURES_DIR / "inventory_update_fixture.xlsx")
    df = sheets[SourceType.INVENTORY_UPDATE]

    cleaned = clean_sheet(df, SourceType.INVENTORY_UPDATE)
    result = build_inventory_master(cleaned)

    assert result.row_errors == []
    assert len(result.records) == 2
    first = result.records[0]
    assert first.product_id == 1068487509
    assert first.catalog_name == "Classy Air Freshener"
    assert first.system_stock_count == 100.0


def test_inventory_update_drops_exact_duplicate_product_id():
    import pandas as pd

    sheets = parse_workbook(FIXTURES_DIR / "inventory_update_fixture.xlsx")
    df = sheets[SourceType.INVENTORY_UPDATE]

    duplicated = clean_sheet(
        pd.concat([df, df.iloc[[1]]], ignore_index=True),
        SourceType.INVENTORY_UPDATE,
    )
    result = build_inventory_master(duplicated)

    assert len(result.records) == 2
    assert result.duplicate_keys_dropped == 1


def test_meesho_listing_parses_unfilled_optional_columns_as_none():
    sheets = parse_workbook(FIXTURES_DIR / "meesho_listing_fixture.xlsx")
    df = sheets[SourceType.MEESHO_LISTING]

    cleaned = clean_sheet(df, SourceType.MEESHO_LISTING)
    result = build_listing_master(cleaned)

    assert result.row_errors == []
    assert len(result.records) == 2

    unfilled = result.records[0]
    assert unfilled.seller_sku == "Aloe_Wipes_100-20*P2"
    assert unfilled.dimensions is None
    assert unfilled.settlement_price is None

    filled = result.records[1]
    assert filled.seller_sku == "BD-B1WF-95PR"
    assert filled.dimensions == "10x10x5"
    assert filled.settlement_price == 99.0
    assert filled.pack_qty == 6


def test_unrecognized_sheet_is_skipped_not_misdetected():
    sheets = parse_workbook(FIXTURES_DIR / "meesho_listing_fixture.xlsx")
    assert SourceType.INVENTORY_UPDATE not in sheets
    assert list(sheets.keys()) == [SourceType.MEESHO_LISTING]

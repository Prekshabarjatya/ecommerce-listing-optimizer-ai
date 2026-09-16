from pathlib import Path

from app.database.repository import (
    count_inventory_items,
    count_listings,
    get_inventory_item,
    get_listing,
    list_low_stock_items,
    upsert_inventory_records,
    upsert_listing_records,
)
from app.ingestion.cleaner import clean_sheet
from app.ingestion.excel_parser import parse_workbook
from app.ingestion.product_master import build_inventory_master, build_listing_master
from app.ingestion.schema_map import SourceType

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"


def _load_inventory_records():
    sheets = parse_workbook(FIXTURES_DIR / "inventory_update_fixture.xlsx")
    cleaned = clean_sheet(sheets[SourceType.INVENTORY_UPDATE], SourceType.INVENTORY_UPDATE)
    return build_inventory_master(cleaned).records


def _load_listing_records():
    sheets = parse_workbook(FIXTURES_DIR / "meesho_listing_fixture.xlsx")
    cleaned = clean_sheet(sheets[SourceType.MEESHO_LISTING], SourceType.MEESHO_LISTING)
    return build_listing_master(cleaned).records


def test_upsert_inventory_then_query(pg_conn):
    records = _load_inventory_records()
    n = upsert_inventory_records(pg_conn, records)

    assert n == 2
    assert count_inventory_items(pg_conn) == 2

    item = get_inventory_item(pg_conn, 1068487509)
    assert item is not None
    assert item["catalog_name"] == "Classy Air Freshener"
    assert item["first_seen_at"] == item["last_updated_at"]


def test_upsert_is_idempotent_and_preserves_first_seen_at(pg_conn):
    records = _load_inventory_records()
    upsert_inventory_records(pg_conn, records)
    first_seen = get_inventory_item(pg_conn, 1068487509)["first_seen_at"]

    upsert_inventory_records(pg_conn, records)

    assert count_inventory_items(pg_conn) == 2
    item = get_inventory_item(pg_conn, 1068487509)
    assert item["first_seen_at"] == first_seen


def test_low_stock_query(pg_conn):
    upsert_inventory_records(pg_conn, _load_inventory_records())
    low = list_low_stock_items(pg_conn, threshold=50)

    assert len(low) == 1
    assert low[0]["system_stock_count"] == 20.0


def test_upsert_listing_then_query(pg_conn):
    n = upsert_listing_records(pg_conn, _load_listing_records())

    assert n == 2
    assert count_listings(pg_conn) == 2

    listing = get_listing(pg_conn, "BD-B1WF-95PR")
    assert listing is not None
    assert listing["settlement_price"] == 99.0
    assert listing["dimensions"] == "10x10x5"

    unfilled = get_listing(pg_conn, "Aloe_Wipes_100-20*P2")
    assert unfilled["settlement_price"] is None

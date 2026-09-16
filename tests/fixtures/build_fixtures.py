"""Regenerate the synthetic .xlsx fixtures used by tests. Run once with:

    python tests/fixtures/build_fixtures.py

Mirrors the real Meesho template quirk where an instructional example row
sits directly under the header (non-numeric id in an id column).
"""

from pathlib import Path

import pandas as pd

FIXTURES_DIR = Path(__file__).resolve().parent


def build_inventory_update_fixture() -> None:
    header_and_instructions = pd.DataFrame(
        [
            {
                "SERIAL NO": "Row identifier",
                "CATALOG NAME": "Catalog name",
                "CATALOG ID": "Catalog id",
                "PRODUCT NAME": "Product name",
                "PRODUCT ID": "Product id",
                "STYLE ID": "Product ID/Style ID",
                "VARIATION ID": "Variation id",
                "VARIATION": "Variation",
                "STOCK": "Stock type (IN_STOCK / OUT_OF_STOCK / ALL)",
                "SYSTEM STOCK COUNT": "Current system stock count",
                "YOUR STOCK COUNT": "Edit this (keep empty if no change in stock)",
            },
            {
                "SERIAL NO": 1,
                "CATALOG NAME": "Classy Air Freshener",
                "CATALOG ID": 562394910,
                "PRODUCT NAME": "Santerra Rose Room Freshener 200g pack-2",
                "PRODUCT ID": 1068487509,
                "STYLE ID": "Airbian-rose-pck2-B",
                "VARIATION ID": 167,
                "VARIATION": "Free Size",
                "STOCK": "ALL",
                "SYSTEM STOCK COUNT": 100,
                "YOUR STOCK COUNT": None,
            },
            {
                "SERIAL NO": 2,
                "CATALOG NAME": "Essential Air Freshener",
                "CATALOG ID": 562394898,
                "PRODUCT NAME": "Santerra Rose Room Freshener 200g pack-1",
                "PRODUCT ID": 1068487494,
                "STYLE ID": "Airbian-rose-pck1-G",
                "VARIATION ID": 167,
                "VARIATION": "Free Size",
                "STOCK": "ALL",
                "SYSTEM STOCK COUNT": 20,
                "YOUR STOCK COUNT": None,
            },
        ]
    )
    header_and_instructions.to_excel(
        FIXTURES_DIR / "inventory_update_fixture.xlsx",
        sheet_name="Inventory-Update-Data-Fill This",
        index=False,
    )


def build_meesho_listing_fixture() -> None:
    df = pd.DataFrame(
        [
            {
                "Seller SKU": "Aloe_Wipes_100-20*P2",
                "Meesho SEO Title": "Santerra Aloe Vera Wet Wipes Pack of 2",
                "Meesho Description": "Skin-friendly wipes for face and hands.",
                "Trending Keywords": "wet wipes, aloe vera, face wipes",
                "Listing ID": None,
                "Bank Settlement Price": None,
                "Pack Qty": 2,
                "Pack/Unit Detail": "2 Pcs Combo / 40 Wipes",
                "Shipping Charges (Indicative Minimum ₹)": None,
                "Suggested Compact Dimension (L x W x H)": None,
                "Volumetric Weight kg": None,
                "Approx Actual Weight kg": None,
                "Chargeable Weight kg": None,
                "Suggested Category 1": "Beauty & Personal Care > Face Wipes",
                "Suggested Category 2": "Skin Care > Wet Wipes",
                "Suggested Category 3": "Travel Essentials > Wet Tissue",
            },
            {
                "Seller SKU": "BD-B1WF-95PR",
                "Meesho SEO Title": "Paperly Premium Tissue Napkin",
                "Meesho Description": "Ultra soft, skin friendly face tissues.",
                "Trending Keywords": "tissue, napkin, eco-friendly",
                "Listing ID": 123456.0,
                "Bank Settlement Price": 99.0,
                "Pack Qty": 6,
                "Pack/Unit Detail": "6 Pack of 30x30",
                "Shipping Charges (Indicative Minimum ₹)": 25.0,
                "Suggested Compact Dimension (L x W x H)": "10x10x5",
                "Volumetric Weight kg": 0.2,
                "Approx Actual Weight kg": 0.25,
                "Chargeable Weight kg": 0.25,
                "Suggested Category 1": "Home & Kitchen > Tissues",
                "Suggested Category 2": "Household > Paper Products",
                "Suggested Category 3": "Office > Supplies",
            },
        ]
    )
    df.to_excel(FIXTURES_DIR / "meesho_listing_fixture.xlsx", sheet_name="Meesho", index=False)


if __name__ == "__main__":
    build_inventory_update_fixture()
    build_meesho_listing_fixture()
    print(f"Wrote fixtures to {FIXTURES_DIR}")

"""Every order title must have a real cover file (spec R6)."""

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SHOPPERS = ROOT / "bookly" / "data" / "shoppers.json"
COVERS = ROOT / "bookly" / "static" / "covers"


def cover_name(title: str) -> str:
    """The page's rule for turning a title into a cover file name (spec R2)."""
    name = title.replace("(eBook)", "").lower()
    name = re.sub(r"[^a-z0-9]+", "-", name)
    return name.strip("-")


def test_cover_name_rule_matches_page_pairs():
    assert cover_name("Project Hail Mary (eBook)") == "project-hail-mary"
    assert cover_name("Tomorrow, and Tomorrow, and Tomorrow") == "tomorrow-and-tomorrow-and-tomorrow"


def test_every_order_title_has_a_cover():
    shoppers = json.loads(SHOPPERS.read_text())
    missing = [
        item["title"]
        for shopper in shoppers.values()
        for order in shopper["orders"]
        for item in order["items"]
        if not (COVERS / f"{cover_name(item['title'])}.jpg").is_file()
    ]
    assert not missing, f"missing cover file for: {', '.join(missing)}"

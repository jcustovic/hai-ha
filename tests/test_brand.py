"""The integration ships its own icon and logo (Home Assistant 2026.3+ reads its `brand/` folder).

Rules from contributors.home-assistant.io/core/integrations/brands: PNG; the icon square, 256 px
(512 for @2x); the logo's shortest side 128-256 px (256-512 for @2x); `dark_` for dark backgrounds.
"""

from __future__ import annotations

from pathlib import Path

import pytest

BRAND = Path(__file__).resolve().parents[1] / "custom_components" / "hai_agent" / "brand"


def _png_size(path: Path) -> tuple[int, int]:
    head = path.read_bytes()[:24]
    assert head[:8] == b"\x89PNG\r\n\x1a\n" and head[12:16] == b"IHDR", f"{path.name} is not a PNG"
    return int.from_bytes(head[16:20], "big"), int.from_bytes(head[20:24], "big")


@pytest.mark.parametrize("prefix", ["", "dark_"])
def test_icons_are_square_at_the_documented_sizes(prefix: str) -> None:
    assert _png_size(BRAND / f"{prefix}icon.png") == (256, 256)
    assert _png_size(BRAND / f"{prefix}icon@2x.png") == (512, 512)


@pytest.mark.parametrize("prefix", ["", "dark_"])
def test_logos_are_landscape_with_the_documented_short_side(prefix: str) -> None:
    for name, low, high in ((f"{prefix}logo.png", 128, 256), (f"{prefix}logo@2x.png", 256, 512)):
        width, height = _png_size(BRAND / name)
        assert width > height and low <= height <= high, name


def test_nothing_unexpected_in_the_brand_folder() -> None:
    names = {p.name for p in BRAND.iterdir()}
    expected = {
        f"{d}{k}{s}.png" for d in ("", "dark_") for k in ("icon", "logo") for s in ("", "@2x")
    }
    assert names == expected

"""Pictures for the shop: catalog pages (cached) built from every VIP skin rendered with a neutral sample player."""
from __future__ import annotations

import io
from functools import lru_cache

from PIL import Image

from services import cards, vip_cards
from services.cards import VIP_STYLES

PAGE_SIZE = 4
EMOJI = {"gold_elite": "🥇", "black_diamond": "💎", "crimson_inferno": "🔥", "ocean_platinum": "🌊", "royal_amethyst": "👑",
         "owner_edition": "👑", "neon_cyber": "⚡", "retro_poster": "🎞️", "backstage_pass": "🎫", "holo_trading": "✨", "fight_night": "🥊"}
KEYS = [k for k in VIP_STYLES if k != "owner_edition"]          # the shop sells these; Owner Edition is never for sale


def pages() -> int:
    return max(1, -(-len(KEYS) // PAGE_SIZE))


def page_keys(page: int) -> list[str]:
    page = max(0, min(page, pages() - 1))
    return KEYS[page * PAGE_SIZE:(page + 1) * PAGE_SIZE]


def page_of(key: str) -> int:
    return KEYS.index(key) // PAGE_SIZE if key in KEYS else 0


@lru_cache(maxsize=1)
def _sample() -> cards.ProfileCard:
    return cards.ProfileCard(cards.Person(7, "Your Name", None), tier="MAIN EVENTER", wins=34, losses=12, knockouts=21, titles=2,
                             finishers=17, streak=7, handle="@yourname", since="Member since 2026",
                             held_belts=["Undisputed WWE Championship", "Intercontinental Championship"])


@lru_cache(maxsize=8)
def catalog_page(page: int) -> bytes:
    """Rendered once per process (about a second per skin), then served from memory."""
    items = []
    for key in page_keys(page):
        card = _sample()
        card.theme = key
        thumb = vip_cards.RENDERERS[key](card).convert("RGB")
        thumb.thumbnail((700, 760), Image.LANCZOS)
        items.append({"title": VIP_STYLES[key][4], "price": VIP_STYLES[key][5], "thumb": thumb})
    return cards.render_shop_page(items, max(0, min(page, pages() - 1)), pages())

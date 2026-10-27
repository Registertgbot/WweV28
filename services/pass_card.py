"""The Season Pass picture: level, XP bar and ten levels of the free and premium reward tracks per page (1280 x 720)."""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Callable

from PIL import Image, ImageDraw

from services.cards import (DIM, GOLD, GOLD_DARK, GOLD_LIGHT, GREEN, MUTED, WHITE, Person, background, clean_name, fit, font, glass, glow,
                            pill, place_avatar, rrect_mask, spaced, to_jpeg, vgrad)

W, H = 1280, 720
PER_PAGE = 10
VIOLET, VIOLET_D = (150, 100, 255), (70, 40, 160)
RARITY_COL = {"common": (190, 198, 214), "rare": (90, 170, 255), "epic": (200, 120, 255), "legendary": (255, 210, 90)}


@dataclass
class PassCard:
    person: Person
    season_number: int
    season_name: str
    level: int
    into: int
    size: int
    xp: int
    max_level: int
    premium: bool
    price: int
    page: int
    claimed: set
    waiting: int
    rank: int | None
    days_left: int
    reward: Callable[[int, str], tuple[str, object]]
    skin_title: Callable[[str], str]


def _check(d, cx, cy, r, col):
    d.line([(cx - r, cy), (cx - r / 3, cy + r * 0.7), (cx + r, cy - r * 0.7)], fill=col, width=5)


def _lock(d, cx, cy, col):
    d.rounded_rectangle((cx - 13, cy - 4, cx + 13, cy + 16), radius=4, fill=col)
    d.arc((cx - 9, cy - 20, cx + 9, cy + 2), 180, 360, fill=col, width=4)


def _icon(img, d, cx, cy, kind, value, dim: bool, card: PassCard):
    fade = (0.45 if dim else 1.0)
    def c(rgb):
        return tuple(int(v * fade + 24 * (1 - fade)) for v in rgb)
    if kind == "coins":
        d.ellipse((cx - 24, cy - 24, cx + 24, cy + 24), fill=c(GOLD_DARK) + (255,), outline=c(GOLD_LIGHT) + (255,), width=3)
        d.ellipse((cx - 15, cy - 15, cx + 15, cy + 15), outline=c(GOLD_LIGHT) + (255,), width=2)
        d.text((cx, cy + 1), "C", font=font("bold", 20), fill=c(GOLD_LIGHT) + (255,), anchor="mm")
        d.text((cx, cy + 48), f"+{value}", font=font("bold", 20), fill=c(WHITE) + (255,), anchor="mm")
    elif kind == "card":
        col = RARITY_COL.get(value, RARITY_COL["common"])
        d.rounded_rectangle((cx - 20, cy - 29, cx + 20, cy + 29), radius=6, fill=c((26, 24, 44)) + (255,), outline=c(col) + (255,), width=3)
        pts = [(cx + (14 if i % 2 == 0 else 6) * math.cos(math.radians(-90 + i * 36)), cy + (14 if i % 2 == 0 else 6) * math.sin(math.radians(-90 + i * 36))) for i in range(10)]
        d.polygon(pts, fill=c(col) + (255,))
        d.text((cx, cy + 48), str(value).upper(), font=font("bold", 13), fill=c(col) + (255,), anchor="mm")
    else:
        d.rounded_rectangle((cx - 26, cy - 24, cx + 26, cy + 24), radius=7, fill=c(VIOLET_D) + (255,), outline=c(GOLD_LIGHT) + (255,), width=3)
        d.polygon([(cx, cy - 15), (cx + 13, cy), (cx, cy + 15), (cx - 13, cy)], fill=c(GOLD_LIGHT) + (255,))
        d.text((cx, cy + 48), card.skin_title(value)[:13].upper(), font=font("bold", 11), fill=c(GOLD_LIGHT) + (255,), anchor="mm")


def render_pass(c: PassCard) -> bytes:
    img = background(W, H, accent=VIOLET_D, seed=c.season_number + 60)
    glow(img, (W / 2, 80), 520, VIOLET, 0.30)
    glass(img, (36, 26, W - 36, 152), 28, tint=VIOLET, tint_alpha=30, shadow=False)
    place_avatar(img, c.person, (104, 90), 84, ring=(GOLD_LIGHT, GOLD_DARK), ring_w=4)
    d = ImageDraw.Draw(img, "RGBA")
    name, nf = fit(d, clean_name(c.person.name, 22), "bold", 32, 360, 18)
    d.text((166, 66), name, font=nf, fill=WHITE, anchor="lm")
    d.text((166, 104), f"SEASON {c.season_number}  •  {c.season_name.upper()}", font=font("bold", 17), fill=GOLD, anchor="lm")
    d.text((166, 130), f"{'RANK #' + str(c.rank) + '  •  ' if c.rank else ''}{c.days_left} DAY{'S' if c.days_left != 1 else ''} LEFT" if c.days_left >= 0 else "SEASON ENDED",
           font=font("medium", 14), fill=MUTED, anchor="lm")
    d.text((640, 74), "LEVEL", font=font("medium", 14), fill=MUTED, anchor="mm")
    d.text((640, 112), str(c.level), font=font("bold", 54), fill=WHITE, anchor="mm")
    bx0, bx1, by = 790, 1210, 98
    d.rounded_rectangle((bx0, by - 11, bx1, by + 11), radius=11, fill=(48, 40, 84))
    pct = 1.0 if c.size == 0 else (c.into / c.size)
    if pct > 0:
        bar = vgrad((max(22, int((bx1 - bx0) * pct)), 22), GOLD_LIGHT, GOLD_DARK).convert("RGBA")
        img.paste(bar, (bx0, by - 11), rrect_mask(bar.size, 11))
    d = ImageDraw.Draw(img, "RGBA")
    d.text((bx1, by - 30), "MAX LEVEL" if c.size == 0 else f"{c.into} / {c.size} XP to Lv {c.level + 1}", font=font("bold", 16), fill=WHITE, anchor="rm")
    d.text((bx0, by - 30), f"{c.xp} XP TOTAL", font=font("medium", 14), fill=MUTED, anchor="lm")
    d.text((bx0, by + 34), "PREMIUM ACTIVE" if c.premium else f"PREMIUM LOCKED  •  {c.price} COINS", font=font("bold", 15), fill=GOLD_LIGHT if c.premium else (200, 170, 255), anchor="lm")

    first = c.page * PER_PAGE + 1
    cw, gap, x0 = 108, 8, 64
    for row, (track, label, top) in enumerate((("free", "FREE TRACK", 186), ("prem", "PREMIUM TRACK", 398))):
        d.text((x0, top - 4), label, font=font("bold", 17), fill=GOLD if track == "prem" else (190, 200, 225), anchor="lm")
        for i in range(PER_PAGE):
            level = first + i
            if level > c.max_level:
                continue
            x = x0 + i * (cw + gap)
            y = top + 14
            reached = level <= c.level
            allowed = track == "free" or c.premium
            claimed = (level, track) in c.claimed
            ready = reached and allowed and not claimed
            kind, value = c.reward(level, track)
            if ready:
                glow(img, (x + cw / 2, y + 85), 110, GOLD if track == "prem" else (120, 200, 255), 0.5)
            panel = Image.new("RGBA", (cw, 170), (0, 0, 0, 0))
            fill = (58, 40, 110, 235) if track == "prem" else (36, 40, 70, 235)
            ImageDraw.Draw(panel).rounded_rectangle((0, 0, cw - 1, 169), radius=18, fill=(fill if (reached or ready) else (24, 22, 40, 220)))
            img.alpha_composite(panel, (x, y))
            d = ImageDraw.Draw(img, "RGBA")
            border = GOLD if ready else ((90, 220, 150) if claimed else ((150, 110, 255) if track == "prem" else (80, 90, 130)))
            d.rounded_rectangle((x, y, x + cw - 1, y + 169), radius=18, outline=border + (255,), width=3 if ready else 2)
            d.text((x + cw / 2, y + 20), f"LV {level}", font=font("bold", 17), fill=WHITE if reached else DIM, anchor="mm")
            _icon(img, d, x + cw // 2, y + 82, kind, value, dim=not (reached and allowed) or claimed, card=c)
            if claimed:
                _check(d, x + cw // 2, y + 146, 11, (90, 220, 150, 255))
            elif ready:
                d.text((x + cw / 2, y + 148), "CLAIM", font=font("bold", 15), fill=GOLD, anchor="mm")
            elif reached and not allowed:
                _lock(d, x + cw // 2, y + 146, (200, 170, 255, 255))
            else:
                d.text((x + cw / 2, y + 148), "LOCKED", font=font("medium", 11), fill=DIM, anchor="mm")
    last = min(c.max_level, first + PER_PAGE - 1)
    spaced(d, (W / 2, 640), f"LEVELS {first} – {last}   •   PAGE {c.page + 1} / {math.ceil(c.max_level / PER_PAGE)}", font("medium", 16), MUTED, spacing=4)
    if c.waiting:
        pill(img, (W // 2 - 150, 664, W // 2 + 150, 700), None, f"{c.waiting} REWARD{'S' if c.waiting != 1 else ''} READY TO CLAIM", font("bold", 16), (20, 14, 40),
             gradient=vgrad((300, 36), GOLD_LIGHT, GOLD_DARK))
    return to_jpeg(img)

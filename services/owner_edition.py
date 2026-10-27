"""The Owner Edition My Card skin: a one-of-one championship belt card. The owner has it automatically; the owner can
give it to anybody with /giveskin owner_edition (it is not sold in the shop). Landscape 1280 x 720.
No official logos are used."""
from __future__ import annotations

import math
import random

from PIL import Image, ImageDraw, ImageFilter, ImageOps

from services.cards import (BELTS, INK, ProfileCard, clean_name, dgrad, draw_crown, drop_shadow, fit, font, glow, rrect_mask, spaced, vgrad)
from services.vip_cards import _poly_mask, _sq, _star

W, H = 1280, 720
G_LIGHT, G_MID, G_DARK = (255, 240, 175), (232, 176, 52), (140, 88, 14)


def _gold_text(img: Image.Image, xy, text: str, f, anchor: str = "mm", palette=None) -> None:
    """Text filled with a brushed-metal gold gradient (bright / dark / bright bands) plus a soft glow."""
    mask = Image.new("L", img.size, 0)
    ImageDraw.Draw(mask).text(xy, text, font=f, fill=255, anchor=anchor)
    box = mask.getbbox()
    if not box:
        return
    w, h = box[2] - box[0], box[3] - box[1]
    band = Image.linear_gradient("L").resize((w, h)).point(lambda v: int(255 * (1 - abs(((v / 255) * 2.2) % 1.0 - 0.5) * 2)))
    dark, mid, light = palette or (G_DARK, G_MID, G_LIGHT)
    fill = ImageOps.colorize(band, black=dark, white=light, mid=mid).convert("RGBA")
    layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
    layer.paste(fill, (box[0], box[1]), mask.crop(box))
    halo = Image.new("RGBA", img.size, (palette[1] if palette else G_MID) + (0,))
    halo.putalpha(mask.filter(ImageFilter.GaussianBlur(10)).point(lambda v: int(v * 0.5)))
    img.alpha_composite(halo)
    img.alpha_composite(layer)


def _stats(c: ProfileCard):
    total = c.wins + c.losses
    return [("WINS", c.wins), ("LOSSES", c.losses), ("WIN RATE", f"{round(100 * c.wins / total) if total else 0}%"),
            ("KNOCKOUTS", c.knockouts), ("FINISHERS", c.finishers), ("BEST STREAK", c.streak)]


def _circle_photo(img, c, center, d, ring=None, ring_w=0):
    cx, cy = center
    if ring:
        outer = d + 2 * ring_w
        m = _poly_mask((outer, outer), [(outer / 2 + outer / 2 * math.cos(math.radians(a)), outer / 2 + outer / 2 * math.sin(math.radians(a))) for a in range(0, 360, 2)])
        img.paste(dgrad((outer, outer), ring[0], ring[1]).convert("RGBA"), (int(cx - outer / 2), int(cy - outer / 2)), m)
    ph = _sq(c.player, d, d).convert("RGBA")
    m = Image.new("L", (d, d), 0)
    ImageDraw.Draw(m).ellipse((0, 0, d - 1, d - 1), fill=255)
    img.paste(ph, (int(cx - d / 2), int(cy - d / 2)), m.resize((d, d), Image.LANCZOS))


def _beams(img, xs, color=(255, 255, 255), alpha=22, blur=14):
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ld = ImageDraw.Draw(layer)
    for x, spread, target in xs:
        ld.polygon([(x - 26, 0), (x + 26, 0), (target + spread, H), (target - spread, H)], fill=color + (alpha,))
    img.alpha_composite(layer.filter(ImageFilter.GaussianBlur(blur)))


def render_image(c: ProfileCard) -> Image.Image:
    rng = random.Random(4)
    img = vgrad((W, H), (30, 4, 8), (8, 2, 4)).convert("RGBA")
    glow(img, (W / 2, H / 2), 860, (220, 30, 40), 0.42)
    _beams(img, [(300, 40, 560), (980, 40, 720)], alpha=18)
    d = ImageDraw.Draw(img, "RGBA")
    gifted = getattr(c, "edition", "owner") == "gift"
    spaced(d, (W / 2, 56), "THE OWNER'S GIFT" if gifted else "THE OWNER'S CHAMPIONSHIP", font("bold", 34), G_LIGHT, spacing=12, shadow=True, max_w=900)
    spaced(d, (W / 2, 100), "GIFTED BY THE OWNER" if gifted else "No. 001 / 001", font("medium", 18), (205, 175, 120), spacing=8, max_w=700)
    strap_y0, strap_y1 = 250, 480
    strap = vgrad((W, strap_y1 - strap_y0), (26, 24, 26), (6, 6, 8)).convert("RGBA")
    img.paste(strap, (0, strap_y0))
    d = ImageDraw.Draw(img, "RGBA")
    for _ in range(3000):
        d.point((rng.randint(0, W), rng.randint(strap_y0, strap_y1)), fill=(255, 255, 255, rng.randint(3, 14)))
    for y in (strap_y0 + 14, strap_y1 - 14):
        for x in range(10, W, 20):
            d.line([(x, y), (x + 10, y)], fill=(214, 24, 34, 230), width=3)
    for x in range(40, W, 74):
        for y in (strap_y0 + 44, strap_y1 - 44):
            d.ellipse((x - 8, y - 8, x + 8, y + 8), fill=G_MID + (255,), outline=G_LIGHT + (255,))
    cx, cy = W // 2, 342
    held = set(c.held_belts or [])
    for sx in (cx - 420, cx + 220):                                           # side plates
        plate = Image.new("RGBA", (200, 250), (0, 0, 0, 0))
        plate.paste(vgrad((200, 250), G_LIGHT, G_DARK).convert("RGBA"), (0, 0), rrect_mask((200, 250), 36))
        pd = ImageDraw.Draw(plate, "RGBA")
        pd.rounded_rectangle((10, 10, 189, 239), radius=28, outline=(110, 66, 12, 255), width=4)
        pd.rounded_rectangle((24, 24, 175, 225), radius=20, fill=(30, 20, 8, 255), outline=G_LIGHT + (255,), width=2)
        for k in range(3):
            idx = k + (0 if sx < cx else 3)
            lit = idx < 5 and BELTS[idx][1] in held
            _star(pd, 100, 70 + k * 56, 17 if lit else 14, G_LIGHT if lit else ((120, 84, 28) if idx < 5 else G_MID))
        img.alpha_composite(plate, (sx, cy - 125))
        d = ImageDraw.Draw(img, "RGBA")
        for ry in (cy - 110, cy + 110):
            for rx in (sx + 24, sx + 176):
                d.ellipse((rx - 6, ry - 6, rx + 6, ry + 6), fill=G_LIGHT + (255,))
    R = 222
    glow(img, (cx, cy), 380, G_MID, 0.5)
    m = _poly_mask((2 * R, 2 * R), [(R + R * math.cos(math.radians(a)), R + R * math.sin(math.radians(a))) for a in range(0, 360, 2)])
    drop_shadow(img, (cx - R, cy - R, cx + R, cy + R), R, blur=24, offset=(0, 14), alpha=170)
    img.paste(vgrad((2 * R, 2 * R), G_LIGHT, G_DARK).convert("RGBA"), (cx - R, cy - R), m)
    d = ImageDraw.Draw(img, "RGBA")
    for k in range(60):                                                        # toothed rim
        a = math.radians(k * 6)
        d.polygon([(cx + (R - 4) * math.cos(a - 0.04), cy + (R - 4) * math.sin(a - 0.04)), (cx + (R + 14) * math.cos(a), cy + (R + 14) * math.sin(a)),
                   (cx + (R - 4) * math.cos(a + 0.04), cy + (R - 4) * math.sin(a + 0.04))], fill=G_MID + (255,))
    ri = R - 34
    d.ellipse((cx - ri, cy - ri, cx + ri, cy + ri), fill=(36, 24, 8, 255), outline=G_LIGHT + (255,), width=3)
    for k in range(7):                                                         # globe: meridians + latitudes
        t = math.radians(k * 180 / 7)
        d.ellipse((cx - ri * abs(math.cos(t)), cy - ri, cx + ri * abs(math.cos(t)), cy + ri), outline=G_MID + (170,), width=2)
    for k in range(-3, 4):
        yy = cy + k * ri / 3.6
        half = math.sqrt(max(0, ri * ri - (yy - cy) ** 2))
        d.line([(cx - half, yy), (cx + half, yy)], fill=G_MID + (170,), width=2)
    _circle_photo(img, c, (cx, cy), 276, ring=(G_LIGHT, G_DARK), ring_w=9)
    draw_crown(img, cx, cy - 142, 130)
    d = ImageDraw.Draw(img, "RGBA")
    name, nf = fit(d, clean_name(c.player.name, 24).upper(), "bold", 58, 620, 30)
    _gold_text(img, (cx, 590), name, nf)
    d = ImageDraw.Draw(img, "RGBA")
    d.text((cx, 636), f"{'HONORARY CHAMPION' if gifted else 'FOUNDER  •  OWNER'}   —   {c.tier}   •   {c.handle or 'WWE ARENA'}", font=font("bold", 22), fill=(235, 215, 170), anchor="mm")
    cells = _stats(c)
    for i, (label, val) in enumerate(cells):
        x = 170 + i * 188
        d.text((x, 676), str(val), font=font("bold", 32), fill=G_LIGHT, anchor="mm")
        d.text((x, 704), label, font=font("medium", 12), fill=(190, 160, 110), anchor="mm")
    return img.convert("RGB")

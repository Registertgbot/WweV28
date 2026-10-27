"""Six VIP My Card skins. Each one has its own layout (not just its own colours):

gold_elite       landscape champion poster      black_diamond   foil trading card (diamond portrait, holo shine)
crimson_inferno  magazine cover                 ocean_platinum  hexagon dashboard with gauges
royal_amethyst   championship belt plate        neon_cyber      cyberpunk HUD with glitch portrait
"""
from __future__ import annotations

import io
import math
import random

from PIL import Image, ImageChops, ImageDraw, ImageEnhance, ImageFilter, ImageOps

from services.cards import (AVATAR_PALETTE, BELTS, GOLD, GOLD_DARK, GOLD_LIGHT, INK, MUTED, DIM, WHITE, ProfileCard,
                            VIP_STYLES, _initials, _paste_clipped, background, circle_mask, clean_name, dgrad,
                            draw_crown, drop_shadow, fit, font, glass, glow, pill, rrect_mask, spaced, to_jpeg,
                            vgrad)


# ------------------------------------------------------------------------------------------ helpers

def _sq(p, w: int, h: int) -> Image.Image:
    """The player's photo cropped to w x h (or a gradient with initials)."""
    if p.avatar:
        try:
            return ImageOps.fit(Image.open(io.BytesIO(p.avatar)).convert("RGB"), (w, h), Image.LANCZOS, centering=(0.5, 0.35))
        except Exception:
            pass
    c1, c2 = AVATAR_PALETTE[abs(p.user_id) % len(AVATAR_PALETTE)]
    im = dgrad((w, h), c1, c2)
    ImageDraw.Draw(im).text((w / 2, h / 2), _initials(p.name), font=font("bold", int(min(w, h) * 0.4)), fill=WHITE, anchor="mm")
    return im


def _poly_mask(size, pts, ss: int = 3) -> Image.Image:
    m = Image.new("L", (size[0] * ss, size[1] * ss), 0)
    ImageDraw.Draw(m).polygon([(x * ss, y * ss) for x, y in pts], fill=255)
    return m.resize(size, Image.LANCZOS)


def _hex(cx, cy, r, rot=0):
    return [(cx + r * math.cos(math.radians(60 * i + rot)), cy + r * math.sin(math.radians(60 * i + rot))) for i in range(6)]


def _gauge(img, center, r, pct, c1, c2, width=16) -> None:
    D, S = 2 * r + 2 * width, 3
    ring = Image.new("L", (D * S, D * S), 0)
    rd = ImageDraw.Draw(ring)
    rd.ellipse((0, 0, D * S - 1, D * S - 1), fill=255)
    rd.ellipse((width * S, width * S, (D - width) * S - 1, (D - width) * S - 1), fill=0)
    arc = Image.new("L", (D * S, D * S), 0)
    if pct > 0:
        ImageDraw.Draw(arc).pieslice((0, 0, D * S - 1, D * S - 1), -90, -90 + 360 * min(pct, 100) / 100 - 0.01, fill=255)
    arc = ImageChops.multiply(arc, ring).resize((D, D), Image.LANCZOS)
    ring = ring.resize((D, D), Image.LANCZOS)
    x, y = int(center[0] - D / 2), int(center[1] - D / 2)
    img.paste(Image.new("RGBA", (D, D), (255, 255, 255, 255)), (x, y), ring.point(lambda v: int(v * 0.14)))
    img.paste(dgrad((D, D), c1, c2).convert("RGBA"), (x, y), arc)


def _glow_text(img, xy, text, f, color, blur=10, anchor="mm", passes=2) -> None:
    layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
    ImageDraw.Draw(layer).text(xy, text, font=f, fill=tuple(color) + (255,), anchor=anchor)
    g = layer.filter(ImageFilter.GaussianBlur(blur))
    for _ in range(passes):
        img.alpha_composite(g)
    img.alpha_composite(layer)


def _star(d, cx, cy, r, fill) -> None:
    pts = []
    for i in range(10):
        rad = r if i % 2 == 0 else r * 0.42
        a = math.radians(-90 + i * 36)
        pts.append((cx + rad * math.cos(a), cy + rad * math.sin(a)))
    d.polygon(pts, fill=fill)


def _stats(c: ProfileCard) -> dict:
    total = c.wins + c.losses
    rate = round(100 * c.wins / total) if total else 0
    ko = round(100 * c.knockouts / c.wins) if c.wins else 0
    held = [n for _, n in BELTS if n in (c.held_belts or [])]
    return {"total": total, "rate": rate, "ko_rate": ko, "belts": len(held), "held": set(c.held_belts or [])}


def _name(c: ProfileCard, limit: int = 40) -> str:
    return clean_name(c.player.name, limit)


# ------------------------------------------------------------------------------------ 1. gold elite

def gold_elite(c: ProfileCard) -> Image.Image:
    W, H = 1280, 720
    st = _stats(c)
    img = background(W, H, accent=(240, 170, 30), seed=c.player.user_id)
    band = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ImageDraw.Draw(band).polygon([(470, 0), (700, 0), (380, H), (150, H)], fill=GOLD + (34,))
    img.alpha_composite(band.filter(ImageFilter.GaussianBlur(2)))
    pw, ph, x0, y0 = 430, 560, 72, 80
    drop_shadow(img, (x0, y0, x0 + pw, y0 + ph), 10, blur=24)
    border = _poly_mask((pw + 18, ph + 18), [(52, 0), (pw + 18, 0), (pw + 18, ph - 34), (pw - 34, ph + 18), (0, ph + 18), (0, 52)])
    img.paste(vgrad((pw + 18, ph + 18), GOLD_LIGHT, GOLD_DARK).convert("RGBA"), (x0 - 9, y0 - 9), border)
    cut = _poly_mask((pw, ph), [(44, 0), (pw, 0), (pw, ph - 38), (pw - 38, ph), (0, ph), (0, 44)])
    img.paste(_sq(c.player, pw, ph).convert("RGBA"), (x0, y0), cut)
    if c.titles:
        draw_crown(img, x0 + 70, y0 + 10, 130)
    d = ImageDraw.Draw(img, "RGBA")
    d.text((570, 100), f"{c.tier}  •  VIP GOLD ELITE", font=font("bold", 22), fill=GOLD, anchor="lm")
    name, nf = fit(d, _name(c).upper(), "bold", 92, 650, 40)
    d.text((570, 176), name, font=nf, fill=WHITE, anchor="lm")
    d.text((570, 244), c.handle or "WWE ARENA SUPERSTAR", font=font("medium", 26), fill=MUTED, anchor="lm")
    d.rectangle((570, 282, 1210, 285), fill=GOLD)
    for i, (label, val, col) in enumerate((("WINS", c.wins, (120, 230, 180)), ("LOSSES", c.losses, (240, 130, 140)), ("KNOCKOUTS", c.knockouts, GOLD))):
        x = 570 + i * 172
        d.text((x, 360), str(val), font=font("bold", 76), fill=col, anchor="lm")
        d.text((x, 420), label, font=font("medium", 19), fill=MUTED, anchor="lm")
    _gauge(img, (1148, 372), 74, st["rate"], GOLD_LIGHT, GOLD_DARK, 16)
    d = ImageDraw.Draw(img, "RGBA")
    d.text((1148, 366), f"{st['rate']}%", font=font("bold", 40), fill=WHITE, anchor="mm")
    d.text((1148, 402), "WIN RATE", font=font("medium", 14), fill=MUTED, anchor="mm")
    for i, (label, val) in enumerate((("FINISHERS", c.finishers), ("BEST STREAK", c.streak), ("TITLES", c.titles))):
        x = 570 + i * 214
        glass(img, (x, 470, x + 196, 542), 18, tint_alpha=24, shadow=False)
        d = ImageDraw.Draw(img, "RGBA")
        d.text((x + 98, 494), str(val), font=font("bold", 30), fill=GOLD_LIGHT, anchor="mm")
        d.text((x + 98, 522), label, font=font("medium", 13), fill=MUTED, anchor="mm")
    for i, (short, full) in enumerate(BELTS):
        x, held = 590 + i * 128, full in st["held"]
        d.ellipse((x - 26, 580, x + 26, 632), fill=None if not held else GOLD, outline=GOLD if held else DIM, width=3)
        if held:
            _star(d, x, 606, 17, INK)
        d.text((x, 656), short, font=font("medium", 12), fill=GOLD_LIGHT if held else DIM, anchor="mm")
    d.text((W - 48, H - 34), "WWE ARENA", font=font("bold", 16), fill=GOLD, anchor="rm")
    return img


# --------------------------------------------------------------------------------- 2. black diamond

def black_diamond(c: ProfileCard) -> Image.Image:
    W, H = 900, 1300
    st = _stats(c)
    base = _sq(c.player, W, H).filter(ImageFilter.GaussianBlur(34))
    base = ImageEnhance.Brightness(base).enhance(0.34).convert("RGBA")
    base.alpha_composite(Image.new("RGBA", (W, H), (8, 10, 18, 120)))
    # holographic shine: a rainbow band swept across the card
    lut = [[int(127 + 127 * math.sin(2 * math.pi * (i / 256) + ph)) for i in range(256)] for ph in (0, 2.1, 4.2)]
    g = Image.linear_gradient("L").resize((2600, 2600)).rotate(-35, resample=Image.BILINEAR).crop((850, 650, 850 + W, 650 + H))
    holo = Image.merge("RGB", tuple(g.point(l) for l in lut)).convert("RGBA")
    holo.putalpha(ImageOps.fit(Image.linear_gradient("L").rotate(90).resize((256, 256)), (W, H)).point(lambda v: int(40 * math.sin(v / 255 * math.pi))))
    base.alpha_composite(holo)
    img = base
    outer_m = rrect_mask((W - 24, H - 24), 46)
    inner_m = Image.new("L", outer_m.size, 0)
    inner_m.paste(rrect_mask((W - 24 - 22, H - 24 - 22), 38), (11, 11))
    ring = ImageChops.subtract(outer_m, inner_m)
    img.paste(dgrad(outer_m.size, (250, 252, 255), (105, 118, 148)).convert("RGBA"), (12, 12), ring)
    d = ImageDraw.Draw(img, "RGBA")
    spaced(d, (W / 2, 62), "BLACK DIAMOND  •  VIP", font("bold", 22), (225, 232, 246), spacing=8, max_w=700)
    cx, cy, r = W // 2, 466, 300
    glow(img, (cx, cy), 420, (190, 205, 235), 0.35)
    outer = _poly_mask((2 * r + 28, 2 * r + 28), [(r + 14, 0), (2 * r + 28, r + 14), (r + 14, 2 * r + 28), (0, r + 14)])
    img.paste(dgrad((2 * r + 28, 2 * r + 28), (250, 252, 255), (120, 132, 160)).convert("RGBA"), (cx - r - 14, cy - r - 14), outer)
    photo = _sq(c.player, 2 * r, 2 * r).convert("RGBA")
    img.paste(photo, (cx - r, cy - r), _poly_mask((2 * r, 2 * r), [(r, 0), (2 * r, r), (r, 2 * r), (0, r)]))
    if c.titles:
        draw_crown(img, cx, cy - r + 6, 130)
    plate = vgrad((700, 100), (248, 250, 255), (150, 160, 184)).convert("RGBA")
    img.paste(plate, (100, 770), rrect_mask((700, 100), 22))
    d = ImageDraw.Draw(img, "RGBA")
    name, nf = fit(d, _name(c).upper(), "bold", 52, 640, 26)
    d.text((W / 2, 812), name, font=nf, fill=INK, anchor="mm")
    d.text((W / 2, 852), f"{c.tier}   {c.handle}".strip(), font=font("medium", 20), fill=(50, 56, 74), anchor="mm")
    rows = [("WINS", c.wins), ("LOSSES", c.losses), ("KNOCKOUTS", c.knockouts), ("FINISHERS", c.finishers),
            ("BEST STREAK", c.streak), ("BELTS HELD", f"{st['belts']} / 5")]
    for i, (label, val) in enumerate(rows):
        y = 925 + i * 53
        d.text((110, y), label, font=font("medium", 22), fill=(205, 212, 228), anchor="lm")
        d.text((W - 110, y), str(val), font=font("bold", 28), fill=WHITE, anchor="rm")
        lw = d.textlength(label, font=font("medium", 22))
        for x in range(int(110 + lw + 16), W - 190, 14):
            d.ellipse((x, y + 4, x + 3, y + 7), fill=(130, 140, 165))
    d.text((W / 2, H - 52), f"No. {abs(c.player.user_id) % 1000000:06d}", font=font("medium", 17), fill=(150, 160, 185), anchor="mm")
    return img


# ------------------------------------------------------------------------------- 3. crimson inferno

def crimson_inferno(c: ProfileCard) -> Image.Image:
    W, H = 1000, 1400
    st = _stats(c)
    photo = ImageEnhance.Color(_sq(c.player, W, H)).enhance(1.2)
    img = photo.convert("RGBA")
    shade = vgrad((W, H), (10, 0, 0), (0, 0, 0)).convert("RGBA")
    mask = Image.linear_gradient("L").resize((W, H)).point(lambda v: int(v * 0.86))
    img.paste(shade, (0, 0), mask)
    top = Image.linear_gradient("L").rotate(180).resize((W, 420)).point(lambda v: int(v * 0.8))
    img.paste(Image.new("RGBA", (W, 420), (0, 0, 0, 255)), (0, 0), top)
    rng = random.Random(c.player.user_id)
    fire = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    fd = ImageDraw.Draw(fire)
    for _ in range(18):
        x, bw = rng.randint(-60, W), rng.randint(100, 260)
        fd.ellipse((x, rng.randint(int(H * 0.72), int(H * 0.9)), x + bw, H + 200), fill=(255, rng.randint(40, 130), 10, rng.randint(70, 130)))
    img.alpha_composite(fire.filter(ImageFilter.GaussianBlur(34)))
    d = ImageDraw.Draw(img, "RGBA")
    d.text((50, 56), "WWE ARENA  •  OFFICIAL VIP EDITION", font=font("bold", 20), fill=(255, 200, 190), anchor="lm")
    d.text((W - 50, 56), f"VOL. {abs(c.player.user_id) % 90 + 10}", font=font("bold", 20), fill=(255, 200, 190), anchor="rm")
    mast, mf = fit(d, "SUPERSTAR", "bold", 218, W - 80, 80)
    d.text((W / 2, 188), mast, font=mf, fill=(255, 255, 255), anchor="mm", stroke_width=3, stroke_fill=(190, 20, 20))
    d.rectangle((50, 300, W - 50, 306), fill=(230, 40, 40))
    d.text((W / 2, 336), f"THE {c.tier} EVERYBODY IS TALKING ABOUT", font=font("medium", 20), fill=(255, 210, 200), anchor="mm")
    name, nf = fit(d, _name(c).upper(), "bold", 112, W - 100, 44)
    nw = int(d.textlength(name, font=nf))
    d.rectangle((40, 842, 70 + nw, 842 + int(nf.size * 1.1)), fill=(210, 25, 30))
    d.text((55, 842 + nf.size * 0.55), name, font=nf, fill=WHITE, anchor="lm")
    heads = [f"{c.wins} WINS. {c.knockouts} KNOCKOUTS.", f"{c.streak}-FIGHT WIN STREAK", f"{c.titles}x CHAMPION" if c.titles else "HUNGRY FOR GOLD"]
    if st["belts"]:
        heads.append(f"HOLDS {st['belts']} CHAMPIONSHIP BELT" + ("S" if st["belts"] > 1 else ""))
    for i, t in enumerate(heads):
        d.text((56, 1010 + i * 62), "•  " + t, font=font("bold", 36), fill=(255, 230, 225), anchor="lm", stroke_width=2, stroke_fill=(60, 0, 0))
    d.ellipse((W - 250, 470, W - 60, 660), fill=(235, 30, 40), outline=(255, 215, 120), width=6)
    d.text((W - 155, 540), "VIP", font=font("bold", 70), fill=WHITE, anchor="mm")
    d.text((W - 155, 604), f"{st['rate']}% WIN RATE", font=font("bold", 17), fill=(255, 225, 215), anchor="mm")
    bx = W - 270
    d.rectangle((bx - 14, H - 190, W - 46, H - 52), fill=WHITE)
    for k in range(34):
        bw = rng.choice((2, 3, 5))
        d.rectangle((bx + k * 6, H - 178, bx + k * 6 + bw, H - 92), fill=INK)
    d.text((bx + 105, H - 72), f"{abs(c.player.user_id) % 10**9:09d}", font=font("medium", 14), fill=INK, anchor="mm")
    return img


# ------------------------------------------------------------------------------- 4. ocean platinum

def ocean_platinum(c: ProfileCard) -> Image.Image:
    W, H = 1280, 720
    st = _stats(c)
    TEAL, ICE, DEEP = (40, 200, 225), (170, 242, 252), (30, 125, 175)
    img = background(W, H, accent=TEAL, seed=c.player.user_id)
    d = ImageDraw.Draw(img, "RGBA")
    for k in range(10):
        y0 = 430 + k * 34
        d.line([(x, y0 + math.sin(x / 80 + k) * 16) for x in range(0, W + 20, 20)], fill=ICE + (max(12, 46 - k * 4),), width=3)
    cx, cy, hr = 300, 330, 220
    glow(img, (cx, cy), 330, TEAL, 0.55)
    for rr, col in ((hr + 22, DEEP + (255,)), (hr + 10, ICE + (255,))):
        m = _poly_mask((2 * rr + 4, 2 * rr + 4), _hex(rr + 2, rr + 2, rr, 30))
        img.paste(Image.new("RGBA", m.size, col), (int(cx - rr - 2), int(cy - rr - 2)), m)
    size = hr * 2 + 4
    m = _poly_mask((size, size), _hex(size / 2, size / 2, hr, 30))
    img.paste(_sq(c.player, size, size).convert("RGBA"), (cx - size // 2, cy - size // 2), m)
    if c.titles:
        draw_crown(img, cx, cy - hr + 4, 120)
    d = ImageDraw.Draw(img, "RGBA")
    d.text((cx, 612), c.tier, font=font("bold", 24), fill=ICE, anchor="mm")
    d.text((560, 92), "OCEAN PLATINUM  •  VIP", font=font("bold", 20), fill=ICE, anchor="lm")
    name, nf = fit(d, _name(c), "bold", 80, 660, 36)
    d.text((560, 158), name, font=nf, fill=WHITE, anchor="lm")
    d.text((560, 214), c.handle or "WWE Arena", font=font("medium", 24), fill=MUTED, anchor="lm")
    gauges = ((st["rate"], f"{st['rate']}%", "WIN RATE"), (st["ko_rate"], f"{st['ko_rate']}%", "KO RATE"),
              (min(100, c.streak * 10), str(c.streak), "BEST STREAK"))
    for i, (pct, val, label) in enumerate(gauges):
        gx = 650 + i * 215
        _gauge(img, (gx, 380), 72, pct, ICE, TEAL, 14)
        d = ImageDraw.Draw(img, "RGBA")
        d.text((gx, 380), val, font=font("bold", 36), fill=WHITE, anchor="mm")
        d.text((gx, 482), label, font=font("medium", 16), fill=MUTED, anchor="mm")
    for i, (label, val) in enumerate((("WINS", c.wins), ("LOSSES", c.losses), ("MATCHES", st["total"]), ("TITLES", c.titles))):
        x = 560 + i * 165
        glass(img, (x, 530, x + 150, 600), 16, tint=ICE, tint_alpha=22, shadow=False)
        d = ImageDraw.Draw(img, "RGBA")
        d.text((x + 75, 553), str(val), font=font("bold", 28), fill=WHITE, anchor="mm")
        d.text((x + 75, 582), label, font=font("medium", 13), fill=MUTED, anchor="mm")
    for i, (short, full) in enumerate(BELTS):
        x, held = 590 + i * 124, full in st["held"]
        hx = _poly_mask((60, 60), _hex(30, 30, 28, 30))
        img.paste(Image.new("RGBA", (60, 60), (ICE + (255,)) if held else (40, 70, 95, 255)), (x - 30, 624), hx)
        d = ImageDraw.Draw(img, "RGBA")
        if held:
            _star(d, x, 654, 15, INK)
        d.text((x, 700), short, font=font("medium", 11), fill=ICE if held else DIM, anchor="mm")
    return img


# ------------------------------------------------------------------------------- 5. royal amethyst

def royal_amethyst(c: ProfileCard) -> Image.Image:
    W, H = 1400, 640
    st = _stats(c)
    PUR, PUR_D, GL = (150, 70, 235), (70, 25, 130), (225, 180, 255)
    img = Image.new("RGBA", (W, H), (14, 8, 22, 255))
    rng = random.Random(c.player.user_id)
    d = ImageDraw.Draw(img, "RGBA")
    for _ in range(2600):                                                  # leather grain
        x, y = rng.randint(0, W), rng.randint(0, H)
        d.point((x, y), fill=(255, 255, 255, rng.randint(4, 14)))
    glow(img, (W / 2, H / 2), 560, PUR, 0.42)
    for y in (34, H - 34):                                                 # stitched seams
        for x in range(24, W - 24, 22):
            d.line([(x, y), (x + 11, y)], fill=GL + (150,), width=3)
    cx, cy = W // 2, 300
    # ornate medallion
    for i in range(56):
        a = math.radians(i * 360 / 56)
        r1, r2 = 262, 292
        d.polygon([(cx + r1 * math.cos(a - 0.05), cy + r1 * math.sin(a - 0.05)), (cx + r2 * math.cos(a), cy + r2 * math.sin(a)),
                   (cx + r1 * math.cos(a + 0.05), cy + r1 * math.sin(a + 0.05))], fill=GOLD + (255,))
    img.paste(dgrad((540, 540), GOLD_LIGHT, GOLD_DARK).convert("RGBA"), (cx - 270, cy - 270), circle_mask(540))
    img.paste(dgrad((492, 492), PUR_D, (30, 10, 60)).convert("RGBA"), (cx - 246, cy - 246), circle_mask(492))
    img.paste(vgrad((444, 444), GOLD_LIGHT, GOLD_DARK).convert("RGBA"), (cx - 222, cy - 222), circle_mask(444))
    img.paste(_sq(c.player, 424, 424).convert("RGBA"), (cx - 212, cy - 212), circle_mask(424))
    if c.titles:
        draw_crown(img, cx, cy - 214, 150)
    d = ImageDraw.Draw(img, "RGBA")
    for side, items in ((-1, (("WINS", c.wins), ("LOSSES", c.losses), ("MATCHES", st["total"]))),
                        (1, (("KNOCKOUTS", c.knockouts), ("FINISHERS", c.finishers), ("BEST STREAK", c.streak)))):
        x0 = 70 if side < 0 else W - 70 - 400
        plate = dgrad((400, 440), (105, 45, 190), (45, 15, 90)).convert("RGBA")
        img.paste(plate, (x0, 90), rrect_mask((400, 440), 40))
        d = ImageDraw.Draw(img, "RGBA")
        d.rounded_rectangle((x0, 90, x0 + 399, 529), radius=40, outline=GOLD + (255,), width=5)
        d.rounded_rectangle((x0 + 14, 104, x0 + 385, 515), radius=30, outline=GL + (120,), width=2)
        for rx, ry in ((x0 + 30, 120), (x0 + 370, 120), (x0 + 30, 500), (x0 + 370, 500)):
            d.ellipse((rx - 6, ry - 6, rx + 6, ry + 6), fill=GOLD_LIGHT)
        for i, (label, val) in enumerate(items):
            y = 180 + i * 120
            d.text((x0 + 200, y), str(val), font=font("bold", 62), fill=WHITE, anchor="mm")
            d.text((x0 + 200, y + 44), label, font=font("medium", 18), fill=GL, anchor="mm")
            if i < 2:
                d.line([(x0 + 70, y + 76), (x0 + 330, y + 76)], fill=GOLD + (130,), width=2)
    rib = [(cx - 330, 520), (cx + 330, 520), (cx + 360, 565), (cx + 330, 610), (cx - 330, 610), (cx - 360, 565)]
    d.polygon(rib, fill=GOLD_DARK)
    img.paste(vgrad((660, 86), GOLD_LIGHT, GOLD_DARK).convert("RGBA"), (cx - 330, 522), _poly_mask((660, 86), [(0, 0), (660, 0), (660, 86), (0, 86)]))
    name, nf = fit(d, _name(c).upper(), "bold", 46, 600, 24)
    d.text((cx, 556), name, font=nf, fill=INK, anchor="mm")
    d.text((cx, 592), f"{c.tier}  •  ROYAL AMETHYST VIP", font=font("bold", 14), fill=(70, 30, 10), anchor="mm")
    return img


# ----------------------------------------------------------------------------------- 6. neon cyber

def neon_cyber(c: ProfileCard) -> Image.Image:
    W, H = 1280, 720
    st = _stats(c)
    CY, PK = (0, 240, 220), (255, 60, 205)
    img = Image.new("RGBA", (W, H), (6, 6, 16, 255))
    glow(img, (330, 330), 420, (120, 30, 200), 0.35)
    glow(img, (1000, 600), 480, (0, 120, 200), 0.30)
    d = ImageDraw.Draw(img, "RGBA")
    horizon = 470
    for i in range(14):
        y = horizon + int((i / 13) ** 2 * (H - horizon))
        d.line([(0, y), (W, y)], fill=PK + (46,), width=2)
    for i in range(-14, 15):
        d.line([(W / 2 + i * 30, horizon), (W / 2 + i * 190, H)], fill=CY + (40,), width=2)
    pw, ph, x0, y0 = 420, 520, 84, 100
    cut = _poly_mask((pw, ph), [(46, 0), (pw, 0), (pw, ph - 46), (pw - 46, ph), (0, ph), (0, 46)])
    photo = _sq(c.player, pw, ph)
    for dx, tint in ((-9, (0, 255, 240)), (9, (255, 40, 200))):                    # glitch: two colour-shifted ghosts
        ghost = ImageChops.multiply(photo, Image.new("RGB", photo.size, tint)).convert("RGBA")
        ghost.putalpha(cut.point(lambda v: int(v * 0.55)))
        _paste_clipped(img, ghost, (x0 + dx, y0 + 2))
    img.paste(photo.convert("RGBA"), (x0, y0), cut)
    sl = Image.new("RGBA", (pw, ph), (0, 0, 0, 0))
    sd = ImageDraw.Draw(sl)
    for y in range(0, ph, 4):
        sd.line([(0, y), (pw, y)], fill=(0, 0, 0, 46))
    sl.putalpha(ImageChops.multiply(sl.getchannel("A"), cut))
    img.alpha_composite(sl, (x0, y0))
    d = ImageDraw.Draw(img, "RGBA")
    outline = [(x0 + 46, y0), (x0 + pw, y0), (x0 + pw, y0 + ph - 46), (x0 + pw - 46, y0 + ph), (x0, y0 + ph), (x0, y0 + 46), (x0 + 46, y0)]
    glowl = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ImageDraw.Draw(glowl).line(outline, fill=CY + (255,), width=6)
    img.alpha_composite(glowl.filter(ImageFilter.GaussianBlur(8)))
    d = ImageDraw.Draw(img, "RGBA")
    d.line(outline, fill=CY + (255,), width=3)
    if c.titles:
        draw_crown(img, x0 + 86, y0 + 6, 120)
    d = ImageDraw.Draw(img, "RGBA")
    d.text((560, 92), "// PLAYER_PROFILE :: VIP.NEON_CYBER", font=font("medium", 20), fill=PK, anchor="lm")
    name, nf = fit(d, _name(c).upper(), "bold", 86, 660, 38)
    _glow_text(img, (560, 170), name, nf, CY, blur=12, anchor="lm")
    d = ImageDraw.Draw(img, "RGBA")
    d.text((560, 232), f"{c.handle or 'ANONYMOUS'}  //  {c.tier}", font=font("medium", 22), fill=(190, 200, 225), anchor="lm")
    bars = (("WIN RATE", st["rate"], f"{st['rate']}%"), ("KO RATE", st["ko_rate"], f"{st['ko_rate']}%"),
            ("FINISHERS", min(100, c.finishers * 4), str(c.finishers)), ("STREAK", min(100, c.streak * 10), str(c.streak)))
    for i, (label, pct, val) in enumerate(bars):
        y = 318 + i * 62
        d.text((560, y), label, font=font("bold", 18), fill=(190, 200, 225), anchor="lm")
        filled = round(pct / 100 * 20)
        for k in range(20):
            x = 720 + k * 22
            t = k / 19
            col = (int(CY[0] + (PK[0] - CY[0]) * t), int(CY[1] + (PK[1] - CY[1]) * t), int(CY[2] + (PK[2] - CY[2]) * t))
            d.polygon([(x + 4, y - 13), (x + 20, y - 13), (x + 16, y + 13), (x, y + 13)], fill=col + ((255,) if k < filled else (38,)))
        d.text((1226, y), val, font=font("bold", 26), fill=WHITE, anchor="rm")
    d.rectangle((560, 590, 1230, 640), fill=(255, 255, 255, 14), outline=CY + (140,), width=2)
    d.text((580, 615), f"W {c.wins}   L {c.losses}   TITLES {c.titles}   BELTS {st['belts']}/5", font=font("bold", 22), fill=CY, anchor="lm")
    return img


# ---- placeholder, replaced below
RENDERERS = {"gold_elite": gold_elite, "black_diamond": black_diamond, "crimson_inferno": crimson_inferno,
             "ocean_platinum": ocean_platinum, "royal_amethyst": royal_amethyst, "neon_cyber": neon_cyber}




# ----------------------------------------------------------------------------------- 7. retro poster

def _rot_paste(img, layer, center, angle) -> None:
    layer = layer.rotate(angle, expand=True, resample=Image.BICUBIC)
    _paste_clipped(img, layer, (int(center[0] - layer.width / 2), int(center[1] - layer.height / 2)))


def retro_poster(c: ProfileCard) -> Image.Image:
    W, H = 1000, 1400
    st = _stats(c)
    img = Image.new("RGBA", (W, H), (255, 130, 30, 255))
    d = ImageDraw.Draw(img, "RGBA")
    cx, cy, n = W // 2, 560, 28
    for i in range(n):                                                    # starburst rays
        a0, a1 = 2 * math.pi * i / n, 2 * math.pi * (i + 1) / n
        d.polygon([(cx, cy), (cx + 1800 * math.cos(a0), cy + 1800 * math.sin(a0)), (cx + 1800 * math.cos(a1), cy + 1800 * math.sin(a1))],
                  fill=(255, 205, 50, 255) if i % 2 else (255, 95, 120, 255))
    dots = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    dd = ImageDraw.Draw(dots)
    for y in range(0, H, 26):                                             # halftone dots
        for x in range(0, W, 26):
            dd.ellipse((x + (13 if (y // 26) % 2 else 0), y, x + (13 if (y // 26) % 2 else 0) + 7, y + 7), fill=(120, 20, 60, 46))
    img.alpha_composite(dots)
    # tilted photo with a thick black outline and a hard offset shadow
    pw, ph = 600, 640
    card = Image.new("RGBA", (pw + 56, ph + 56), (0, 0, 0, 0))
    ImageDraw.Draw(card).rectangle((16, 16, pw + 55, ph + 55), fill=(20, 10, 30, 255))
    ImageDraw.Draw(card).rectangle((0, 0, pw + 39, ph + 39), fill=(255, 255, 255, 255), outline=(20, 10, 30, 255), width=8)
    card.paste(_sq(c.player, pw, ph).convert("RGBA"), (20, 20))
    _rot_paste(img, card, (cx, 520), -5)
    d = ImageDraw.Draw(img, "RGBA")
    if c.titles:
        draw_crown(img, cx - 140, 190, 150)
    d = ImageDraw.Draw(img, "RGBA")
    d.polygon([(40, 60), (420, 40), (440, 120), (60, 140)], fill=(210, 30, 50, 255), outline=(20, 10, 30, 255))
    d.text((240, 92), "SUPERSTAR!", font=font("bold", 44), fill=(255, 255, 255), anchor="mm", stroke_width=3, stroke_fill=(20, 10, 30))
    name, nf = fit(d, _name(c).upper(), "bold", 118, W - 120, 52)
    for off in (9, 6, 3):
        d.text((cx + off, 928 + off), name, font=nf, fill=(20, 10, 30), anchor="mm", stroke_width=6, stroke_fill=(20, 10, 30))
    d.text((cx, 928), name, font=nf, fill=(255, 240, 70), anchor="mm", stroke_width=6, stroke_fill=(20, 10, 30))
    d.text((cx, 1010), f"{c.tier}  •  {c.handle or 'WWE ARENA'}", font=font("bold", 30), fill=(255, 255, 255), anchor="mm", stroke_width=3, stroke_fill=(20, 10, 30))
    for k, (label, val) in enumerate((("WINS", c.wins), ("K.O.", c.knockouts), ("STREAK", c.streak), ("TITLES", c.titles))):
        x0 = 60 + k * 225
        d.rounded_rectangle((x0 + 7, 1087, x0 + 207, 1237), radius=18, fill=(20, 10, 30))
        d.rounded_rectangle((x0, 1080, x0 + 200, 1230), radius=18, fill=(255, 255, 255), outline=(20, 10, 30), width=6)
        d.text((x0 + 100, 1137), str(val), font=font("bold", 66), fill=(210, 30, 50), anchor="mm")
        d.text((x0 + 100, 1200), label, font=font("bold", 24), fill=(20, 10, 30), anchor="mm")
    sx, sy = 810, 330                                                     # starburst sticker
    pts = [(sx + (130 if i % 2 == 0 else 96) * math.cos(math.pi * i / 12), sy + (130 if i % 2 == 0 else 96) * math.sin(math.pi * i / 12)) for i in range(24)]
    d.polygon(pts, fill=(255, 235, 60), outline=(20, 10, 30))
    d.text((sx, sy - 22), f"{st['rate']}%", font=font("bold", 66), fill=(210, 30, 50), anchor="mm", stroke_width=2, stroke_fill=(20, 10, 30))
    d.text((sx, sy + 38), "WIN RATE", font=font("bold", 24), fill=(20, 10, 30), anchor="mm")
    d.text((W / 2, 1320), "WWE ARENA  •  VIP RETRO EDITION", font=font("bold", 26), fill=(255, 255, 255), anchor="mm", stroke_width=3, stroke_fill=(20, 10, 30))
    return img


# -------------------------------------------------------------------------------- 8. backstage pass

def backstage_pass(c: ProfileCard) -> Image.Image:
    W, H = 760, 1240
    st = _stats(c)
    img = Image.new("RGBA", (W, H), (14, 14, 22, 255))
    glow(img, (W / 2, 420), 600, (220, 40, 50), 0.28)
    d = ImageDraw.Draw(img, "RGBA")
    for sx in (W // 2 - 60, W // 2 + 60):                                 # lanyard straps meeting at the clip
        strap = [(sx - 34 + (-1 if sx < W // 2 else 1) * 230, 0), (sx + 34 + (-1 if sx < W // 2 else 1) * 230, 0), (W // 2 + 34, 170), (W // 2 - 34, 170)]
        d.polygon(strap, fill=(205, 30, 45, 255))
        d.line([strap[0], strap[3]], fill=(255, 255, 255, 90), width=3)
    d.rounded_rectangle((W // 2 - 44, 150, W // 2 + 44, 226), radius=14, fill=(170, 175, 190), outline=(90, 95, 110), width=4)
    d.rounded_rectangle((W // 2 - 26, 188, W // 2 + 26, 206), radius=8, fill=(14, 14, 22))
    bx0, by0, bx1, by1 = 70, 250, W - 70, H - 50
    drop_shadow(img, (bx0, by0, bx1, by1), 40, blur=24, offset=(0, 18), alpha=150)
    img.paste(Image.new("RGBA", (bx1 - bx0, by1 - by0), (246, 246, 250, 255)), (bx0, by0), rrect_mask((bx1 - bx0, by1 - by0), 40))
    d = ImageDraw.Draw(img, "RGBA")
    d.rounded_rectangle((W // 2 - 62, by0 + 18, W // 2 + 62, by0 + 38), radius=10, fill=(14, 14, 22))      # the slot
    band = Image.new("RGBA", (bx1 - bx0, 96), (205, 30, 45, 255))
    img.paste(band, (bx0, by0 + 64), _poly_mask(band.size, [(0, 0), (band.width, 0), (band.width, 96), (0, 96)]))
    d = ImageDraw.Draw(img, "RGBA")
    spaced(d, (W / 2, by0 + 112), "ALL ACCESS", font("bold", 44), (255, 255, 255), spacing=10, max_w=520)
    pw = 380
    img.paste(Image.new("RGBA", (pw + 16, pw + 16), (20, 20, 30, 255)), (W // 2 - pw // 2 - 8, by0 + 196), rrect_mask((pw + 16, pw + 16), 26))
    img.paste(_sq(c.player, pw, pw).convert("RGBA"), (W // 2 - pw // 2, by0 + 204), rrect_mask((pw, pw), 20))
    if c.titles:
        draw_crown(img, W // 2, by0 + 232, 96)
    d = ImageDraw.Draw(img, "RGBA")
    name, nf = fit(d, _name(c).upper(), "bold", 56, bx1 - bx0 - 50, 28)
    d.text((W / 2, by0 + 640), name, font=nf, fill=(18, 18, 28), anchor="mm")
    d.text((W / 2, by0 + 690), f"{c.tier}  •  {c.handle or 'SUPERSTAR'}", font=font("medium", 24), fill=(90, 94, 110), anchor="mm")
    d.rectangle((bx0 + 40, by0 + 725, bx1 - 40, by0 + 728), fill=(205, 30, 45))
    for k, (label, val) in enumerate((("WINS", c.wins), ("LOSSES", c.losses), ("K.O.", c.knockouts), ("BELTS", st["belts"]))):
        x = bx0 + 40 + k * ((bx1 - bx0 - 80) // 4) + ((bx1 - bx0 - 80) // 8)
        d.text((x, by0 + 772), str(val), font=font("bold", 44), fill=(18, 18, 28), anchor="mm")
        d.text((x, by0 + 812), label, font=font("medium", 16), fill=(100, 104, 120), anchor="mm")
    rng = random.Random(c.player.user_id)
    x = bx0 + 50
    for _ in range(46):                                                   # barcode
        w = rng.choice((3, 4, 6))
        d.rectangle((x, by0 + 860, x + w, by0 + 930), fill=(18, 18, 28))
        x += w + rng.choice((3, 4))
        if x > bx1 - 200:
            break
    d.text((bx1 - 56, by0 + 895), f"ID {abs(c.player.user_id) % 10**6:06d}", font=font("bold", 22), fill=(18, 18, 28), anchor="rm")
    stamp = Image.new("RGBA", (300, 120), (0, 0, 0, 0))
    sd = ImageDraw.Draw(stamp)
    sd.rounded_rectangle((4, 4, 295, 115), radius=16, outline=(205, 30, 45, 220), width=7)
    sd.text((150, 60), "VIP", font=font("bold", 76), fill=(205, 30, 45, 220), anchor="mm")
    _rot_paste(img, stamp, (bx1 - 135, by0 + 540), -14)
    return img


# --------------------------------------------------------------------------------- 9. holo trading

def holo_trading(c: ProfileCard) -> Image.Image:
    W, H = 900, 1260
    st = _stats(c)
    img = Image.new("RGBA", (W, H), (20, 14, 40, 255))
    img.paste(dgrad((W, H), (255, 240, 160), (190, 120, 40)).convert("RGBA"), (0, 0), rrect_mask((W, H), 54))
    img.paste(dgrad((W - 44, H - 44), (30, 24, 64), (12, 10, 32)).convert("RGBA"), (22, 22), rrect_mask((W - 44, H - 44), 40))
    d = ImageDraw.Draw(img, "RGBA")
    name, nf = fit(d, _name(c), "bold", 50, 520, 26)
    d.text((70, 96), name, font=nf, fill=(255, 245, 200), anchor="lm")
    d.text((W - 70, 96), f"HP {min(999, c.wins * 10 + 50)}", font=font("bold", 40), fill=(255, 120, 120), anchor="rm")
    ax0, ay0, ax1, ay1 = 60, 150, W - 60, 700
    art = _sq(c.player, ax1 - ax0, ay1 - ay0).convert("RGBA")
    lut = [[int(127 + 127 * math.sin(2 * math.pi * (i / 256) + ph)) for i in range(256)] for ph in (0, 2.1, 4.2)]
    g = Image.linear_gradient("L").resize((2000, 2000)).rotate(-40, resample=Image.BILINEAR).crop((600, 600, 600 + art.width, 600 + art.height))
    holo = Image.merge("RGB", tuple(g.point(l) for l in lut)).convert("RGBA")
    holo.putalpha(Image.new("L", art.size, 70))
    art.alpha_composite(holo)
    rng = random.Random(c.player.user_id)
    ad = ImageDraw.Draw(art, "RGBA")
    for _ in range(36):                                                   # sparkles
        sx, sy, r = rng.randint(0, art.width), rng.randint(0, art.height), rng.randint(3, 10)
        ad.polygon([(sx, sy - r * 2), (sx + r // 2, sy - 1), (sx + r * 2, sy), (sx + r // 2, sy + 1), (sx, sy + r * 2), (sx - r // 2, sy + 1), (sx - r * 2, sy), (sx - r // 2, sy - 1)],
                   fill=(255, 255, 255, rng.randint(110, 230)))
    img.paste(art, (ax0, ay0), rrect_mask(art.size, 22))
    d = ImageDraw.Draw(img, "RGBA")
    d.rounded_rectangle((ax0, ay0, ax1, ay1), radius=22, outline=(255, 235, 150), width=6)
    if c.titles:
        draw_crown(img, ax0 + 74, ay0 + 52, 84)
    d = ImageDraw.Draw(img, "RGBA")
    stars = {"ROOKIE": 1, "CONTENDER": 2, "MAIN EVENTER": 3, "LEGEND": 4}.get(c.tier, 1)
    pill(img, (ax0, ay1 + 20, ax0 + 330, ay1 + 62), None, f"{c.tier}", font("bold", 22), (30, 20, 50), gradient=vgrad((330, 42), (255, 245, 180), (230, 170, 60)))
    d = ImageDraw.Draw(img, "RGBA")
    for i in range(4):
        _star(d, ax1 - 40 - i * 52, ay1 + 41, 20, (255, 225, 90) if i < stars else (80, 70, 110))
    moves = [("Knockout", c.knockouts, "●●●" if c.knockouts >= 10 else "●●"), ("Finisher", c.finishers, "●●"), ("Win streak", c.streak, "●")]
    for i, (label, val, dots) in enumerate(moves):
        y = ay1 + 130 + i * 78
        for k in range(len(dots)):
            d.ellipse((ax0 + 8 + k * 30, y - 11, ax0 + 30 + k * 30, y + 11), fill=(255, 215, 90))
        d.text((ax0 + 130, y), label, font=font("bold", 34), fill=(255, 245, 210), anchor="lm")
        d.text((ax1 - 6, y), str(val), font=font("bold", 44), fill=(255, 120, 120), anchor="rm")
        if i < 2:
            d.line([(ax0, y + 38), (ax1, y + 38)], fill=(255, 235, 150, 60), width=2)
    d.rectangle((ax0, H - 190, ax1, H - 187), fill=(255, 235, 150, 120))
    d.text((ax0 + 6, H - 150), f"wins {c.wins}   losses {c.losses}   belts {st['belts']}/5", font=font("medium", 26), fill=(200, 190, 230), anchor="lm")
    d.text((ax0 + 6, H - 100), f"{c.handle or 'WWE Arena'}  •  {st['rate']}% win rate", font=font("medium", 22), fill=(160, 150, 200), anchor="lm")
    d.text((ax1 - 6, H - 100), f"No. {abs(c.player.user_id) % 1000:03d}/999", font=font("bold", 22), fill=(255, 225, 120), anchor="rm")
    return img


# ----------------------------------------------------------------------------------- 10. fight night

def fight_night(c: ProfileCard) -> Image.Image:
    W, H = 1280, 720
    st = _stats(c)
    img = Image.new("RGBA", (W, H), (6, 6, 12, 255))
    glow(img, (260, 360), 560, (220, 40, 30), 0.5)
    glow(img, (1040, 300), 520, (60, 110, 230), 0.42)
    beams = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    bd = ImageDraw.Draw(beams)
    for x, wd in ((150, 90), (330, 70), (900, 90), (1100, 70)):           # stage spotlights
        bd.polygon([(x, 0), (x + wd, 0), (x + wd + 260, H), (x - 260, H)], fill=(255, 255, 255, 18))
    img.alpha_composite(beams.filter(ImageFilter.GaussianBlur(10)))
    d = ImageDraw.Draw(img, "RGBA")
    pw, ph, x0, y0 = 470, 640, 60, 40
    photo = _sq(c.player, pw, ph).convert("RGBA")
    shade = Image.linear_gradient("L").resize((pw, ph)).point(lambda v: int(v * 0.55))
    photo.paste(Image.new("RGBA", (pw, ph), (0, 0, 0, 255)), (0, 0), shade)
    drop_shadow(img, (x0, y0, x0 + pw, y0 + ph), 8, blur=26)
    img.paste(photo, (x0, y0), _poly_mask((pw, ph), [(0, 0), (pw - 60, 0), (pw, 60), (pw, ph), (60, ph), (0, ph - 60)]))
    d = ImageDraw.Draw(img, "RGBA")
    d.line([(x0, y0), (x0 + pw - 60, y0), (x0 + pw, y0 + 60), (x0 + pw, y0 + ph), (x0 + 60, y0 + ph), (x0, y0 + ph - 60), (x0, y0)], fill=(230, 50, 40), width=6)
    if c.titles:
        draw_crown(img, x0 + 110, y0 + 80, 130)
    d = ImageDraw.Draw(img, "RGBA")
    d.rectangle((590, 52, 1230, 108), fill=(220, 40, 30))
    spaced(d, (910, 80), "TONIGHT  •  MAIN EVENT", font("bold", 30), (255, 255, 255), spacing=8, max_w=600)
    name, nf = fit(d, _name(c).upper(), "bold", 98, 650, 44)
    d.text((590, 190), name, font=nf, fill=WHITE, anchor="lm", stroke_width=2, stroke_fill=(0, 0, 0))
    d.text((590, 262), f"{c.tier}  •  {c.handle or 'WWE ARENA'}", font=font("medium", 26), fill=(180, 190, 215), anchor="lm")
    d.text((590, 400), f"{c.wins}-{c.losses}", font=font("bold", 170), fill=(255, 255, 255), anchor="lm", stroke_width=3, stroke_fill=(220, 40, 30))
    d.text((594, 508), "RECORD  (WINS - LOSSES)", font=font("medium", 20), fill=(150, 160, 190), anchor="lm")
    ko = st["ko_rate"]
    d.text((590, 566), f"{c.knockouts} K.O.", font=font("bold", 46), fill=(255, 215, 80), anchor="lm")
    d.rounded_rectangle((830, 548, 1230, 584), radius=18, fill=(40, 44, 66))
    if ko:
        d.rounded_rectangle((830, 548, 830 + max(20, int(400 * ko / 100)), 584), radius=18, fill=(230, 50, 40))
    d.text((1030, 566), f"{ko}% KO RATE", font=font("bold", 20), fill=WHITE, anchor="mm")
    for i, (short, full) in enumerate(BELTS):
        x, held = 610 + i * 130, full in st["held"]
        d.ellipse((x - 22, 630, x + 22, 674), fill=(255, 205, 70) if held else None, outline=(255, 205, 70) if held else (80, 86, 110), width=3)
        if held:
            _star(d, x, 652, 14, (30, 20, 5))
        d.text((x + 34, 652), short, font=font("bold", 12), fill=(255, 215, 120) if held else (90, 96, 120), anchor="lm")
    return img


RENDERERS.update({"retro_poster": retro_poster, "backstage_pass": backstage_pass, "holo_trading": holo_trading, "fight_night": fight_night})


def render_vip_card(c: ProfileCard) -> bytes:
    if c.theme == "owner_edition":
        from services.owner_edition import render_image
        return to_jpeg(render_image(c), quality=93)
    return to_jpeg(RENDERERS[c.theme](c), quality=92)

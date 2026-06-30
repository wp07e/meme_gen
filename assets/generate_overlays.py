"""Generate transparent PNG overlays for Vitaroast 10-in-1 mushroom coffee."""
from pathlib import Path
from PIL import Image, ImageColor, ImageDraw, ImageFont

ASSETS_DIR = Path(__file__).resolve().parent

# Brand colors
MAIN = "#4a3230"      # dark coffee brown
SECONDARY = "#ded2c2" # cream
TRIM = "#be5c39"      # terracotta/rust


def get_font(size, bold=False):
    """Best-effort system font selection."""
    candidates = [
        "/System/Library/Fonts/Helvetica.ttc",
        "/System/Library/Fonts/Helvetica.dfont",
        "/System/Library/Fonts/Arial.ttf",
        "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
        "/Library/Fonts/Arial.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    ]
    if bold:
        candidates.insert(0, "/System/Library/Fonts/Supplemental/Arial Bold.ttf")
    for path in candidates:
        try:
            return ImageFont.truetype(path, size)
        except Exception:
            continue
    return ImageFont.load_default()


def save(img, name):
    out = ASSETS_DIR / name
    img.save(out, "PNG")
    print(f"Saved {out} ({img.width}x{img.height})")


def draw_rounded_rect(draw, xy, radius, fill, outline=None, width=1):
    """Draw a rounded rectangle."""
    x1, y1, x2, y2 = xy
    draw.rounded_rectangle(xy, radius=radius, fill=fill, outline=outline, width=width)


def make_watermark():
    """Small @vitaroast watermark for top-right corner."""
    w, h = 240, 70
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    font = get_font(26, bold=True)
    text = "@vitaroast"
    bbox = draw.textbbox((0, 0), text, font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]

    # subtle dark pill background so it reads on light or dark videos
    pad = 10
    pill_w = tw + pad * 2
    pill_h = th + pad * 2
    x1 = w - pill_w - 8
    y1 = (h - pill_h) // 2
    draw.rounded_rectangle(
        [x1, y1, x1 + pill_w, y1 + pill_h],
        radius=pill_h // 2,
        fill=(*ImageColor.getrgb(MAIN), 200),
        outline=TRIM,
        width=2,
    )

    draw.text(
        (x1 + pad - bbox[0], y1 + pad - bbox[1] + 1),
        text,
        font=font,
        fill=SECONDARY,
    )
    save(img, "watermark.png")


def make_bottom_bar():
    """Lower-third brand bar for 9:16 reels (1080x160)."""
    w, h = 1080, 160
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # Main brown bar
    bar_h = 130
    y_offset = h - bar_h
    draw.rectangle([0, y_offset, w, h], fill=MAIN)

    # Terracotta trim lines
    draw.rectangle([0, y_offset, w, y_offset + 6], fill=TRIM)
    draw.rectangle([0, h - 6, w, h], fill=TRIM)

    # Left accent block
    draw.rectangle([0, y_offset, 12, h], fill=TRIM)

    # Product text
    font_title = get_font(44, bold=True)
    font_sub = get_font(22)
    title = "10 IN 1 MUSHROOM COFFEE"
    sub = "Focus • Energy • Immunity • Gut Health"

    tb = draw.textbbox((0, 0), title, font=font_title)
    sb = draw.textbbox((0, 0), sub, font=font_sub)

    margin_x = 40
    title_y = y_offset + 26
    draw.text((margin_x, title_y), title, font=font_title, fill=SECONDARY)
    draw.text((margin_x, title_y + tb[3] - tb[1] + 8), sub, font=font_sub, fill=TRIM)

    # @vitaroast handle on the right
    font_handle = get_font(24, bold=True)
    handle = "@vitaroast"
    hb = draw.textbbox((0, 0), handle, font=font_handle)
    draw.text((w - hb[2] + hb[0] - margin_x, title_y + 10), handle, font=font_handle, fill=SECONDARY)

    save(img, "bottom-bar.png")


def make_end_card():
    """Full-screen 9:16 end card (1080x1920)."""
    w, h = 1080, 1920
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # Cream background panel
    margin = 80
    draw.rounded_rectangle(
        [margin, 260, w - margin, h - 260],
        radius=40,
        fill=SECONDARY,
        outline=TRIM,
        width=8,
    )

    # Top terracotta band
    draw.rounded_rectangle(
        [margin, 260, w - margin, 360],
        radius=40,
        fill=TRIM,
    )
    # Flatten bottom of band so it joins the panel
    draw.rectangle([margin, 320, w - margin, 370], fill=TRIM)

    font_brand = get_font(62, bold=True)
    brand = "VITAROAST"
    bb = draw.textbbox((0, 0), brand, font=font_brand)
    draw.text(
        ((w - (bb[2] - bb[0])) // 2, 275),
        brand,
        font=font_brand,
        fill=SECONDARY,
    )

    font_title = get_font(84, bold=True)
    title = "10 IN 1"
    line2 = "MUSHROOM"
    line3 = "COFFEE"
    y = 480
    for line in [title, line2, line3]:
        tb = draw.textbbox((0, 0), line, font=font_title)
        draw.text(((w - (tb[2] - tb[0])) // 2, y), line, font=font_title, fill=MAIN)
        y += tb[3] - tb[1] + 20

    # Benefit pills
    font_pill = get_font(28, bold=True)
    benefits = ["FOCUS", "ENERGY", "IMMUNITY", "GUT HEALTH"]
    pill_h = 58
    y_pills = y + 60
    x_start = margin + 40
    x = x_start
    for benefit in benefits:
        pb = draw.textbbox((0, 0), benefit, font=font_pill)
        pw = (pb[2] - pb[0]) + 36
        draw.rounded_rectangle(
            [x, y_pills, x + pw, y_pills + pill_h],
            radius=pill_h // 2,
            fill=MAIN,
            outline=TRIM,
            width=3,
        )
        draw.text(
            (x + 18, y_pills + 10),
            benefit,
            font=font_pill,
            fill=SECONDARY,
        )
        x += pw + 16

    # CTA
    font_cta = get_font(40, bold=True)
    cta = "FOLLOW @vitaroast"
    cb = draw.textbbox((0, 0), cta, font=font_cta)
    cta_y = h - 420
    draw.rounded_rectangle(
        [(w - (cb[2] - cb[0]) - 60) // 2, cta_y - 14, (w + (cb[2] - cb[0]) + 60) // 2, cta_y + cb[3] - cb[1] + 26],
        radius=50,
        fill=TRIM,
    )
    draw.text(
        ((w - (cb[2] - cb[0])) // 2, cta_y - 6),
        cta,
        font=font_cta,
        fill=SECONDARY,
    )

    # Small handle at very bottom
    font_small = get_font(24)
    handle = "www.vitaroast.com  •  @vitaroast"
    hb = draw.textbbox((0, 0), handle, font=font_small)
    draw.text(
        ((w - (hb[2] - hb[0])) // 2, h - 330),
        handle,
        font=font_small,
        fill=MAIN,
    )

    save(img, "end-card.png")


def make_top_badge():
    """Small '10 in 1' badge for top-left corner."""
    w, h = 220, 80
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    draw.rounded_rectangle([0, 0, w, h], radius=20, fill=TRIM, outline=SECONDARY, width=3)

    font_big = get_font(36, bold=True)
    font_small = get_font(18, bold=True)
    tb = draw.textbbox((0, 0), "10 in 1", font=font_big)
    sb = draw.textbbox((0, 0), "MUSHROOM COFFEE", font=font_small)

    draw.text(((w - (tb[2] - tb[0])) // 2, 8), "10 in 1", font=font_big, fill=SECONDARY)
    draw.text(((w - (sb[2] - sb[0])) // 2, 46), "MUSHROOM COFFEE", font=font_small, fill=MAIN)

    save(img, "top-badge.png")


if __name__ == "__main__":
    make_watermark()
    make_bottom_bar()
    make_end_card()
    make_top_badge()
    print("Done.")

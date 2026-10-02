import os
import math
import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageFilter
import cv2

# Configuration
WIDTH = 720
HEIGHT = 1280
FPS = 30
OUTPUT_FILE = "pickpickles_promo_ad.mp4"

EMOJI_FONT_PATH = "C:/Windows/Fonts/seguiemj.ttf"

# Cache for font instances
FONT_CACHE = {}

def get_font(name="arialbd.ttf", size=32):
    key = (name, size)
    if key not in FONT_CACHE:
        font_path = os.path.join("C:/Windows/Fonts", name)
        if os.path.exists(font_path):
            try:
                FONT_CACHE[key] = ImageFont.truetype(font_path, size)
            except Exception:
                FONT_CACHE[key] = ImageFont.load_default()
        else:
            FONT_CACHE[key] = ImageFont.load_default()
    return FONT_CACHE[key]

def get_emoji_font(size=32):
    key = ("emoji", size)
    if key not in FONT_CACHE:
        if os.path.exists(EMOJI_FONT_PATH):
            try:
                FONT_CACHE[key] = ImageFont.truetype(EMOJI_FONT_PATH, size)
            except Exception:
                FONT_CACHE[key] = get_font("segoeui.ttf", size)
        else:
            FONT_CACHE[key] = get_font("segoeui.ttf", size)
    return FONT_CACHE[key]

def is_emoji_char(ch):
    c = ord(ch)
    return (
        0x1F000 <= c <= 0x1FFFF or
        0x2600 <= c <= 0x27BF or
        0xFE00 <= c <= 0xFE0F or
        0x2300 <= c <= 0x23FF or
        c in (0x200D, 0x20E3, 0x2728, 0x2714, 0x2705)
    )

def get_mixed_tokens(text):
    tokens = []
    curr = ''
    curr_em = None
    for ch in text:
        em = is_emoji_char(ch)
        if curr_em is None:
            curr_em = em
            curr += ch
        elif curr_em == em:
            curr += ch
        else:
            tokens.append((curr, curr_em))
            curr = ch
            curr_em = em
    if curr:
        tokens.append((curr, curr_em))
    return tokens

def draw_mixed_text(draw, x, y, text, font, size, fill, anchor="mm"):
    tokens = get_mixed_tokens(text)
    emoji_font = get_emoji_font(size)
    
    items = []
    total_w = 0
    max_h = 0
    for tok, is_em in tokens:
        f = emoji_font if is_em else font
        try:
            bbox = draw.textbbox((0, 0), tok, font=f, embedded_color=is_em)
        except Exception:
            bbox = draw.textbbox((0, 0), tok, font=f)
        w = max(0, bbox[2] - bbox[0])
        h = max(0, bbox[3] - bbox[1])
        # Add tiny spacing after emoji
        if is_em:
            w += int(size * 0.15)
        items.append((tok, is_em, f, w, h))
        total_w += w
        if h > max_h:
            max_h = h

    if anchor == "mm":
        start_x = x - total_w / 2
        start_y = y - max_h / 2
    elif anchor == "lm":
        start_x = x
        start_y = y - max_h / 2
    elif anchor == "rm":
        start_x = x - total_w
        start_y = y - max_h / 2
    else: # top-left
        start_x = x
        start_y = y
        
    cur_x = start_x
    for tok, is_em, f, w, h in items:
        if is_em:
            try:
                draw.text((cur_x, start_y), tok, font=f, embedded_color=True)
            except Exception:
                draw.text((cur_x, start_y), tok, font=f, fill=fill)
        else:
            draw.text((cur_x, start_y), tok, font=f, fill=fill)
        cur_x += w

# Fonts
FONT_TITLE_XL = get_font("segoeuib.ttf", 48)
FONT_TITLE_LG = get_font("segoeuib.ttf", 38)
FONT_SUBTITLE = get_font("segoeui.ttf", 25)
FONT_BADGE = get_font("segoeuib.ttf", 22)
FONT_PRICE = get_font("arialbd.ttf", 30)

# Colors
BG_TOP = (24, 18, 14)
BG_BOTTOM = (12, 10, 8)
ACCENT_GOLD = (245, 180, 50)
ACCENT_GREEN = (46, 204, 113)
TEXT_WHITE = (255, 255, 255)
TEXT_MUTED = (210, 205, 195)
CARD_BG = (28, 24, 20, 225)
CARD_BORDER = (80, 70, 60, 190)

# Product list
PRODUCTS = [
    {
        "img": "media/products/pickled_mixed_veggies.webp",
        "badge": "✨ SIGNATURE CRUNCH",
        "title": "Pickled Mixed Veggies",
        "subtitle": "Crunchy cucumbers, carrots, peppers & garlic",
        "price": "450 BDT",
        "tag": "Zero Heavy Oils"
    },
    {
        "img": "media/products/classic_dill_pickles.webp",
        "badge": "🥒 LOUD DELI CRUNCH",
        "title": "Classic Dill Pickles",
        "subtitle": "Fresh local cucumbers steeped in cold dill brine",
        "price": "400 BDT",
        "tag": "Zero Heavy Oils"
    },
    {
        "img": "media/products/pickled_beetroot.webp",
        "badge": "🩸 RUBY CRIMSON",
        "title": "Pickled Beetroot",
        "subtitle": "Sweet-earthy tang for burgers, salads & shawarma",
        "price": "400 BDT",
        "tag": "Artisanal Spiced"
    },
    {
        "img": "media/products/pickled_deshi_onions.webp",
        "badge": "🧅 TEHARI & BIRYANI PAIR",
        "title": "Pickled Deshi Onions",
        "subtitle": "Sliced onion rings in spiced cane vinegar brine",
        "price": "350 BDT",
        "tag": "Deshi Flavor"
    },
    {
        "img": "media/products/pickled_green_peppers.webp",
        "badge": "🌶️ CRISP & FIERY",
        "title": "Pickled Green Peppers",
        "subtitle": "Vibrant fiery kick with garlic & mustard seeds",
        "price": "350 BDT",
        "tag": "Fire Hot"
    },
    {
        "img": "media/products/pickled_mango.webp",
        "badge": "🥭 SWEET & SPICY",
        "title": "Pickled Mango Spears",
        "subtitle": "Ripe mango spears infused with red chili flakes",
        "price": "450 BDT",
        "tag": "Gourmet Cut"
    },
    {
        "img": "media/products/pickled_pineapple.webp",
        "badge": "🍍 TROPICAL PUNCH",
        "title": "Pickled Pineapple",
        "subtitle": "Golden juicy pineapple chunks with chili kick",
        "price": "450 BDT",
        "tag": "Sweet & Tangy"
    },
    {
        "img": "media/products/pickled_quail_eggs.webp",
        "badge": "🥚 SAVORY DELICACY",
        "title": "Pickled Quail Eggs",
        "subtitle": "Protein-rich gourmet delicacy in aromatic brine",
        "price": "500 BDT",
        "tag": "Chef Special"
    },
    {
        "img": "media/products/pickled_grapes.webp",
        "badge": "🍇 JUICY BURST",
        "title": "Pickled Seedless Grapes",
        "subtitle": "Crisp sweet-tangy burst with gentle chili warmth",
        "price": "550 BDT",
        "tag": "Gourmet Luxury"
    }
]

def create_background():
    base = Image.new("RGB", (WIDTH, HEIGHT), BG_TOP)
    draw = ImageDraw.Draw(base)
    for y in range(HEIGHT):
        ratio = y / HEIGHT
        r = int(BG_TOP[0] * (1 - ratio) + BG_BOTTOM[0] * ratio)
        g = int(BG_TOP[1] * (1 - ratio) + BG_BOTTOM[1] * ratio)
        b = int(BG_TOP[2] * (1 - ratio) + BG_BOTTOM[2] * ratio)
        draw.line([(0, y), (WIDTH, y)], fill=(r, g, b))
    
    glow = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
    glow_draw = ImageDraw.Draw(glow)
    center_x, center_y = WIDTH // 2, int(HEIGHT * 0.45)
    radius = 320
    for r in range(radius, 0, -10):
        alpha = int(45 * (1 - (r / radius) ** 1.5))
        glow_draw.ellipse(
            (center_x - r, center_y - r, center_x + r, center_y + r),
            fill=(220, 140, 40, alpha)
        )
    
    base = Image.alpha_composite(base.convert("RGBA"), glow).convert("RGB")
    return base

BASE_BG = create_background()

def draw_rounded_rect(draw, bbox, radius, fill, outline=None, width=1):
    draw.rounded_rectangle(bbox, radius=radius, fill=fill, outline=outline, width=width)

def render_intro_frame(progress):
    frame = BASE_BG.copy().convert("RGBA")
    overlay = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)

    alpha = min(255, int(progress * 4 * 255))

    # Top Brand Tag
    tag_text = "🥒 PICKPICKLES ARTISAN"
    draw_rounded_rect(draw, (WIDTH//2 - 185, 230, WIDTH//2 + 185, 285), 25, (40, 32, 24, 230), outline=(245, 180, 50, 200), width=2)
    draw_mixed_text(draw, WIDTH//2, 258, tag_text, FONT_BADGE, 22, ACCENT_GOLD, anchor="mm")

    # Main Hook Text
    draw_mixed_text(draw, WIDTH//2, 365, "Tired of Oily Pickles? 🚫", FONT_TITLE_XL, 46, (255, 110, 110, alpha), anchor="mm")
    draw_mixed_text(draw, WIDTH//2, 435, "Experience 100% Pure Crunch ✨", FONT_TITLE_LG, 36, (255, 255, 255, alpha), anchor="mm")

    # Features Box
    card_y = 530
    draw_rounded_rect(draw, (70, card_y, WIDTH - 70, card_y + 380), 24, (25, 20, 16, 235), outline=(80, 70, 60, 200), width=2)
    
    features = [
        ("✨ Zero Heavy Oils", "Crafted in artisanal cane vinegar brine"),
        ("🥒 Audible Crisp Crunch", "Local farm-fresh cucumbers & veggies"),
        ("🌶️ 9 Gourmet Flavors", "From Deshi Onions to Pickled Quail Eggs"),
        ("🇧🇩 Handcrafted in Dhaka", "Fresh, small batches with zero preservatives")
    ]

    for i, (f_title, f_sub) in enumerate(features):
        fy = card_y + 40 + (i * 82)
        draw_mixed_text(draw, 110, fy, f_title, get_font("segoeuib.ttf", 25), 25, ACCENT_GOLD, anchor="lm")
        draw.text((110, fy + 32), f_sub, font=get_font("segoeui.ttf", 19), fill=TEXT_MUTED)

    # Bottom Prompt
    pulse_alpha = int(180 + 75 * math.sin(progress * 10))
    draw_mixed_text(draw, WIDTH//2, 1040, "DISCOVER THE LINEUP ⬇️", get_font("arialbd.ttf", 28), 28, (255, 255, 255, pulse_alpha), anchor="mm")

    frame = Image.alpha_composite(frame, overlay).convert("RGB")
    return frame

def render_product_frame(product_idx, progress):
    prod = PRODUCTS[product_idx]
    frame = BASE_BG.copy().convert("RGBA")
    overlay = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)

    # Load and scale product image with gentle Ken-Burns zoom
    img_path = prod["img"]
    if os.path.exists(img_path):
        p_img = Image.open(img_path).convert("RGBA")
        
        zoom = 1.0 + 0.12 * progress
        orig_w, orig_h = p_img.size
        target_h = int(600 * zoom)
        target_w = int(orig_w * (target_h / orig_h))
        
        p_img_resized = p_img.resize((target_w, target_h), Image.Resampling.LANCZOS)
        
        paste_x = (WIDTH - target_w) // 2
        paste_y = 170 + int((600 - target_h) / 2)

        shadow = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
        s_draw = ImageDraw.Draw(shadow)
        s_draw.ellipse((WIDTH//2 - 180, 720, WIDTH//2 + 180, 790), fill=(0, 0, 0, 160))
        shadow = shadow.filter(ImageFilter.GaussianBlur(15))
        frame = Image.alpha_composite(frame, shadow)

        frame.paste(p_img_resized, (paste_x, paste_y), p_img_resized)

    # Top Category Badge
    badge_w = 360
    draw_rounded_rect(draw, (WIDTH//2 - badge_w//2, 100, WIDTH//2 + badge_w//2, 150), 24, (35, 28, 22, 230), outline=(245, 180, 50, 220), width=2)
    draw_mixed_text(draw, WIDTH//2, 125, prod["badge"], FONT_BADGE, 22, ACCENT_GOLD, anchor="mm")

    # Bottom Glassmorphic Card
    card_top = 810
    card_h = 330
    draw_rounded_rect(draw, (40, card_top, WIDTH - 40, card_top + card_h), 28, CARD_BG, outline=CARD_BORDER, width=2)

    # Product Title
    draw.text((WIDTH//2, card_top + 45), prod["title"], font=FONT_TITLE_LG, fill=TEXT_WHITE, anchor="mm")

    # Subtitle / Description
    draw.text((WIDTH//2, card_top + 105), prod["subtitle"], font=FONT_SUBTITLE, fill=TEXT_MUTED, anchor="mm")

    # Tag & Price Row
    tag_w = 210
    draw_rounded_rect(draw, (75, card_top + 170, 75 + tag_w, card_top + 230), 20, (46, 125, 50, 220))
    draw_mixed_text(draw, 75 + tag_w//2, card_top + 200, f"✓ {prod['tag']}", get_font("segoeuib.ttf", 22), 22, (255, 255, 255), anchor="mm")

    # Price Pill
    price_w = 210
    draw_rounded_rect(draw, (WIDTH - 75 - price_w, card_top + 170, WIDTH - 75, card_top + 230), 20, (245, 180, 50, 230))
    draw.text((WIDTH - 75 - price_w//2, card_top + 200), prod["price"], font=FONT_PRICE, fill=(20, 15, 10), anchor="mm")

    # Product counter
    draw.text((WIDTH//2, card_top + 285), f"Product {product_idx + 1} of {len(PRODUCTS)}  •  pickpickles.xyz", font=get_font("segoeui.ttf", 20), fill=(160, 150, 140), anchor="mm")

    frame = Image.alpha_composite(frame, overlay).convert("RGB")
    return frame

def render_outro_frame(progress):
    frame = BASE_BG.copy().convert("RGBA")
    overlay = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)

    # Logo Card
    draw_rounded_rect(draw, (55, 170, WIDTH - 55, 475), 28, (30, 24, 18, 235), outline=(245, 180, 50, 230), width=2)
    
    draw_mixed_text(draw, WIDTH//2, 235, "🥒 PICKPICKLES", FONT_TITLE_XL, 48, ACCENT_GOLD, anchor="mm")
    draw.text((WIDTH//2, 305), "Artisan Pickles • Zero Heavy Oils", font=get_font("segoeuib.ttf", 30), fill=TEXT_WHITE, anchor="mm")
    draw.text((WIDTH//2, 365), "Crafted in Hand-Steeped Cane Vinegar Brine", font=FONT_SUBTITLE, fill=TEXT_MUTED, anchor="mm")
    draw_mixed_text(draw, WIDTH//2, 420, "★ ★ ★ ★ ★ 100% Authentic Bangladeshi Taste", get_font("segoeuib.ttf", 22), 22, (255, 215, 0), anchor="mm")

    # CTA Box
    cta_y = 525
    draw_rounded_rect(draw, (55, cta_y, WIDTH - 55, cta_y + 375), 28, (20, 18, 15, 240), outline=(46, 204, 113, 220), width=2)

    draw.text((WIDTH//2, cta_y + 55), "ORDER ONLINE TODAY", font=get_font("arialbd.ttf", 36), fill=ACCENT_GREEN, anchor="mm")
    
    btn_y = cta_y + 115
    draw_rounded_rect(draw, (90, btn_y, WIDTH - 90, btn_y + 80), 25, ACCENT_GOLD)
    draw_mixed_text(draw, WIDTH//2, btn_y + 40, "🌐 www.pickpickles.xyz", get_font("arialbd.ttf", 30), 30, (20, 15, 10), anchor="mm")

    draw_mixed_text(draw, WIDTH//2, cta_y + 250, "🚚 Cash on Delivery Across Bangladesh", get_font("segoeuib.ttf", 23), 23, TEXT_WHITE, anchor="mm")
    draw_mixed_text(draw, WIDTH//2, cta_y + 295, "📦 Fresh Small Batches • Safe Packaging", get_font("segoeui.ttf", 21), 21, TEXT_MUTED, anchor="mm")

    pulse_alpha = int(200 + 55 * math.sin(progress * 12))
    draw_mixed_text(draw, WIDTH//2, 1040, "LIMITED BATCH AVAILABLE • ORDER NOW 🛒", get_font("arialbd.ttf", 26), 26, (255, 200, 80, pulse_alpha), anchor="mm")

    frame = Image.alpha_composite(frame, overlay).convert("RGB")
    return frame

def main():
    print(f"Starting video generation: {WIDTH}x{HEIGHT} @ {FPS}fps...")
    fourcc = cv2.VideoWriter_fourcc(*'mp4v')
    out = cv2.VideoWriter(OUTPUT_FILE, fourcc, FPS, (WIDTH, HEIGHT))

    if not out.isOpened():
        print("Error: Could not open VideoWriter.")
        return

    INTRO_FRAMES = int(FPS * 2.8)
    PRODUCT_FRAMES = int(FPS * 2.2)
    OUTRO_FRAMES = int(FPS * 3.5)
    TRANSITION_FRAMES = int(FPS * 0.4)

    total_scenes = 1 + len(PRODUCTS) + 1
    current_frame = 0
    total_estimated_frames = INTRO_FRAMES + (len(PRODUCTS) * PRODUCT_FRAMES) + OUTRO_FRAMES

    def pil_to_cv2(pil_img):
        return cv2.cvtColor(np.array(pil_img), cv2.COLOR_RGB2BGR)

    print(f"Total scenes: {total_scenes} (~{total_estimated_frames // FPS} seconds)")

    # 1. INTRO
    print("Rendering Intro with colored emojis...")
    last_frame_bgr = None
    for f in range(INTRO_FRAMES):
        prog = f / max(1, INTRO_FRAMES - 1)
        pil_frame = render_intro_frame(prog)
        bgr = pil_to_cv2(pil_frame)
        out.write(bgr)
        last_frame_bgr = bgr
        current_frame += 1

    # 2. PRODUCTS
    for idx in range(len(PRODUCTS)):
        print(f"Rendering Product {idx + 1}/{len(PRODUCTS)}: {PRODUCTS[idx]['title']}...")
        for f in range(PRODUCT_FRAMES):
            prog = f / max(1, PRODUCT_FRAMES - 1)
            pil_frame = render_product_frame(idx, prog)
            bgr = pil_to_cv2(pil_frame)
            
            if f < TRANSITION_FRAMES and last_frame_bgr is not None:
                alpha = f / TRANSITION_FRAMES
                blended = cv2.addWeighted(last_frame_bgr, 1.0 - alpha, bgr, alpha, 0)
                out.write(blended)
            else:
                out.write(bgr)
            
            last_frame_bgr = bgr
            current_frame += 1

    # 3. OUTRO
    print("Rendering Outro with colored emojis...")
    for f in range(OUTRO_FRAMES):
        prog = f / max(1, OUTRO_FRAMES - 1)
        pil_frame = render_outro_frame(prog)
        bgr = pil_to_cv2(pil_frame)
        
        if f < TRANSITION_FRAMES and last_frame_bgr is not None:
            alpha = f / TRANSITION_FRAMES
            blended = cv2.addWeighted(last_frame_bgr, 1.0 - alpha, bgr, alpha, 0)
            out.write(blended)
        else:
            out.write(bgr)
            
        last_frame_bgr = bgr
        current_frame += 1

    out.release()
    print(f"Successfully generated {OUTPUT_FILE} ({current_frame} frames, {current_frame/FPS:.1f}s)")

if __name__ == "__main__":
    main()

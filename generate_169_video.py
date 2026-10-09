import os
import math
import subprocess
import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageFilter
import cv2
import scipy.io.wavfile as wav
import imageio_ffmpeg

# Configuration (16:9 Landscape)
WIDTH = 1280
HEIGHT = 720
FPS = 30
TEMP_VIDEO = "temp_video_169_no_audio.mp4"
TEMP_AUDIO = "temp_audio_169_track.wav"
FINAL_OUTPUT_FILE = "pickpickles_169_ad_with_music.mp4"

EMOJI_FONT_PATH = "C:/Windows/Fonts/seguiemj.ttf"
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
        0x2300 <= c <= 0x23FF or
        0x2B00 <= c <= 0x2BFF or  # ⭐ (0x2B50)
        0x2700 <= c <= 0x27BF or  # ✅ (0x2705), ✨ (0x2728), ✔️ (0x2714)
        0x2600 <= c <= 0x26FF or  # ⚡, ☕, etc.
        0xFE00 <= c <= 0xFE0F or
        c in (0x200D, 0x20E3)
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
    else:
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

# Fonts (16:9 Scale)
FONT_TITLE_XL = get_font("segoeuib.ttf", 46)
FONT_TITLE_LG = get_font("segoeuib.ttf", 36)
FONT_SUBTITLE = get_font("segoeui.ttf", 22)
FONT_BADGE = get_font("segoeuib.ttf", 20)

# Colors
BG_TOP = (20, 16, 12)
BG_BOTTOM = (10, 8, 6)
ACCENT_GOLD = (245, 180, 50)
ACCENT_GREEN = (46, 204, 113)
TEXT_WHITE = (255, 255, 255)
TEXT_MUTED = (215, 210, 200)
CARD_BG = (25, 21, 17, 230)
CARD_BORDER = (90, 75, 60, 200)

# Product catalog (NO OIL MENTION, NO PRICES)
PRODUCTS = [
    {
        "img": "media/products/classic_dill_pickles.webp",
        "badge": "🥒 LOUD DELI CRUNCH",
        "title": "Classic Dill Pickles",
        "subtitle": "Fresh local cucumbers steeped in cold dill brine",
        "tag1": "Audible Crisp Bite",
        "tag2": "Cane Vinegar"
    },
    {
        "img": "media/products/pickled_mango.webp",
        "badge": "🥭 SWEET & SPICY",
        "title": "Pickled Mango Spears",
        "subtitle": "Ripe mango spears infused with red chili flakes",
        "tag1": "Sweet & Tangy",
        "tag2": "Gourmet Cut"
    },
    {
        "img": "media/products/pickled_mixed_veggies.webp",
        "badge": "✨ SIGNATURE CRUNCH",
        "title": "Pickled Mixed Veggies",
        "subtitle": "Crunchy cucumbers, carrots, bell peppers & garlic",
        "tag1": "Farm Fresh",
        "tag2": "Whole Spices"
    },
    {
        "img": "media/products/pickled_beetroot.webp",
        "badge": "🩸 RUBY CRIMSON",
        "title": "Pickled Beetroot",
        "subtitle": "Sweet-earthy tang for burgers, salads & bowls",
        "tag1": "Natural Ruby Hue",
        "tag2": "Artisanal Spiced"
    },
    {
        "img": "media/products/pickled_deshi_onions.webp",
        "badge": "🧅 TEHARI & BIRYANI PAIR",
        "title": "Pickled Deshi Onions",
        "subtitle": "Sliced onion rings in spiced cane vinegar brine",
        "tag1": "Crisp Zesty Bite",
        "tag2": "Authentic Deshi"
    },
    {
        "img": "media/products/pickled_pineapple.webp",
        "badge": "🍍 TROPICAL PUNCH",
        "title": "Pickled Pineapple",
        "subtitle": "Golden juicy pineapple chunks with chili kick",
        "tag1": "Tropical Tang",
        "tag2": "Spiced Brine"
    },
    {
        "img": "media/products/pickled_green_peppers.webp",
        "badge": "🌶️ CRISP & FIERY",
        "title": "Pickled Green Peppers",
        "subtitle": "Vibrant fiery kick with garlic & mustard seeds",
        "tag1": "Fire Hot Crunch",
        "tag2": "Whole Mustard"
    },
    {
        "img": "media/products/pickled_grapes.webp",
        "badge": "🍇 JUICY BURST",
        "title": "Pickled Seedless Grapes",
        "subtitle": "Plump grapes with sweet-tangy burst & gentle chili",
        "tag1": "Gourmet Luxury",
        "tag2": "Juicy & Spiced"
    },
    {
        "img": "media/products/pickled_bell_peppers.webp",
        "badge": "🫑 VIBRANT CRUNCH",
        "title": "Pickled Bell Peppers",
        "subtitle": "Colorful capsicum slices in sweet-tangy cane brine",
        "tag1": "Farm Fresh",
        "tag2": "Sweet & Crisp"
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
    
    glow_draw.ellipse((100, 60, 640, 600), fill=(235, 150, 45, 45))
    glow_draw.ellipse((750, 100, 1200, 550), fill=(200, 120, 30, 35))
    
    glow = glow.filter(ImageFilter.GaussianBlur(30))
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

    # Top Brand Pill
    tag_text = "🥒 PICKPICKLES ARTISAN"
    draw_rounded_rect(draw, (WIDTH//2 - 180, 50, WIDTH//2 + 180, 100), 22, (35, 28, 20, 230), outline=(245, 180, 50, 220), width=2)
    draw_mixed_text(draw, WIDTH//2, 75, tag_text, FONT_BADGE, 20, ACCENT_GOLD, anchor="mm")

    # Main Big Hook (No oil references)
    draw_mixed_text(draw, WIDTH//2, 160, "Craving Real Crunch? 🥒", FONT_TITLE_XL, 46, (255, 215, 80, alpha), anchor="mm")
    draw_mixed_text(draw, WIDTH//2, 225, "Experience 100% Pure Crunchy Taste ✨", FONT_TITLE_LG, 34, (255, 255, 255, alpha), anchor="mm")

    # 4 Features in 2x2 Grid
    features = [
        ("✨ Artisanal Cane Vinegar", "Steeped in pure aromatic spice-infused brine"),
        ("🥒 Audible Fresh Crunch", "Local farm-fresh cucumbers & vibrant veggies"),
        ("🌶️ 9 Handcrafted Flavors", "Sweet, tangy, savory & fiery spiced varieties"),
        ("🇧🇩 Handcrafted in Dhaka", "Small gourmet batches with zero preservatives")
    ]

    card_w = 480
    card_h = 110
    coords = [
        (130, 310), (670, 310),
        (130, 445), (670, 445)
    ]

    for i, (f_title, f_sub) in enumerate(features):
        cx, cy = coords[i]
        draw_rounded_rect(draw, (cx, cy, cx + card_w, cy + card_h), 20, (25, 20, 15, 240), outline=(85, 72, 60, 200), width=2)
        draw_mixed_text(draw, cx + 30, cy + 38, f_title, get_font("segoeuib.ttf", 23), 23, ACCENT_GOLD, anchor="lm")
        draw.text((cx + 30, cy + 72), f_sub, font=get_font("segoeui.ttf", 17), fill=TEXT_MUTED)

    # Bottom Prompt
    pulse_alpha = int(190 + 65 * math.sin(progress * 10))
    draw_mixed_text(draw, WIDTH//2, 630, "DISCOVER OUR ARTISAN LINEUP ⬇️", get_font("arialbd.ttf", 25), 25, (255, 255, 255, pulse_alpha), anchor="mm")

    frame = Image.alpha_composite(frame, overlay).convert("RGB")
    return frame

PRODUCT_CANVAS_CACHE = {}

def get_product_canvas(product_idx, width, height, target_h, center_x, center_y):
    key = (product_idx, width, height, target_h, center_x, center_y)
    if key not in PRODUCT_CANVAS_CACHE:
        prod = PRODUCTS[product_idx]
        img_path = prod["img"]
        canvas = np.zeros((height, width, 4), dtype=np.uint8)
        if os.path.exists(img_path):
            p_img = Image.open(img_path).convert("RGBA")
            orig_w, orig_h = p_img.size
            base_w = int(orig_w * (target_h / orig_h))
            base_resized = p_img.resize((base_w, target_h), Image.Resampling.LANCZOS)
            base_np = np.array(base_resized)
            
            paste_x = int(center_x - base_w / 2)
            paste_y = int(center_y - target_h / 2)
            canvas[paste_y:paste_y+target_h, paste_x:paste_x+base_w] = base_np
        PRODUCT_CANVAS_CACHE[key] = canvas
    return PRODUCT_CANVAS_CACHE[key]

def render_product_frame(product_idx, progress):
    prod = PRODUCTS[product_idx]
    frame = BASE_BG.copy().convert("RGBA")
    overlay = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)

    # Left Side: Product Jar (Subpixel smooth zoom, cv2.INTER_CUBIC)
    target_h = 525
    center_jar_x = 350.0
    center_jar_y = 95.0 + target_h / 2.0

    base_canvas = get_product_canvas(product_idx, WIDTH, HEIGHT, target_h, center_jar_x, center_jar_y)
    smooth_prog = 0.5 - 0.5 * math.cos(progress * math.pi)
    zoom = 1.0 + 0.08 * smooth_prog

    M = cv2.getRotationMatrix2D((center_jar_x, center_jar_y), 0, zoom)
    zoomed_rgba = cv2.warpAffine(base_canvas, M, (WIDTH, HEIGHT), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_CONSTANT, borderValue=(0,0,0,0))
    zoomed_pil = Image.fromarray(zoomed_rgba)

    # Contact shadow underneath jar
    shadow = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
    s_draw = ImageDraw.Draw(shadow)
    shadow_w = int(170 * zoom)
    s_draw.ellipse((int(center_jar_x - shadow_w), 580, int(center_jar_x + shadow_w), 645), fill=(0, 0, 0, 180))
    shadow = shadow.filter(ImageFilter.GaussianBlur(18))
    frame = Image.alpha_composite(frame, shadow)

    # Paste smoothly zoomed jar
    frame = Image.alpha_composite(frame, zoomed_pil)

    # Right Side: Glassmorphic Info Card (16:9 Landscape)
    card_x = 650
    card_y = 100
    card_w = 550
    card_h = 510
    draw_rounded_rect(draw, (card_x, card_y, card_x + card_w, card_y + card_h), 28, CARD_BG, outline=CARD_BORDER, width=2)

    # Category Badge
    badge_w = 340
    draw_rounded_rect(draw, (card_x + 40, card_y + 35, card_x + 40 + badge_w, card_y + 85), 20, (35, 28, 20, 235), outline=(245, 180, 50, 220), width=2)
    draw_mixed_text(draw, card_x + 40 + badge_w//2, card_y + 60, prod["badge"], FONT_BADGE, 20, ACCENT_GOLD, anchor="mm")

    # Product Title
    draw.text((card_x + 40, card_y + 125), prod["title"], font=FONT_TITLE_LG, fill=TEXT_WHITE)

    # Subtitle
    draw.text((card_x + 40, card_y + 190), prod["subtitle"], font=FONT_SUBTITLE, fill=TEXT_MUTED)

    # Benefit Tag Pills (Horizontal)
    pill_w = 210
    # Pill 1
    draw_rounded_rect(draw, (card_x + 40, card_y + 265, card_x + 40 + pill_w, card_y + 325), 18, (38, 115, 45, 230))
    draw_mixed_text(draw, card_x + 40 + pill_w//2, card_y + 295, f"✅ {prod['tag1']}", get_font("segoeuib.ttf", 20), 20, (255, 255, 255), anchor="mm")

    # Pill 2
    draw_rounded_rect(draw, (card_x + 65 + pill_w, card_y + 265, card_x + 65 + pill_w * 2, card_y + 325), 18, (230, 150, 30, 230))
    draw_mixed_text(draw, card_x + 65 + pill_w + pill_w//2, card_y + 295, f"✨ {prod['tag2']}", get_font("segoeuib.ttf", 20), 20, (20, 15, 10), anchor="mm")

    # Artisanal Guarantee Line
    draw_mixed_text(draw, card_x + 40, card_y + 390, "✨ 100% Natural Freshness • Hand-Steeped Cane Vinegar", get_font("segoeui.ttf", 19), 19, ACCENT_GOLD, anchor="lm")

    # Counter footer
    draw.text((card_x + 40, card_y + 445), f"Item {product_idx + 1} of {len(PRODUCTS)}  •  www.pickpickles.xyz", font=get_font("segoeui.ttf", 19), fill=(165, 155, 145))

    frame = Image.alpha_composite(frame, overlay).convert("RGB")
    return frame

def render_outro_frame(progress):
    frame = BASE_BG.copy().convert("RGBA")
    overlay = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)

    # Left Card: Brand Story
    card1_x = 80
    card_y = 110
    card_w = 520
    card_h = 470
    draw_rounded_rect(draw, (card1_x, card_y, card1_x + card_w, card_y + card_h), 28, (30, 24, 18, 240), outline=(245, 180, 50, 230), width=2)
    
    draw_mixed_text(draw, card1_x + card_w//2, card_y + 80, "🥒 PICKPICKLES", FONT_TITLE_XL, 44, ACCENT_GOLD, anchor="mm")
    draw.text((card1_x + card_w//2, card_y + 155), "Artisanal Pickles • 100% Fresh & Crisp", font=get_font("segoeuib.ttf", 27), fill=TEXT_WHITE, anchor="mm")
    draw.text((card1_x + card_w//2, card_y + 215), "Handcrafted in Spiced Cane Vinegar Brine", font=FONT_SUBTITLE, fill=TEXT_MUTED, anchor="mm")
    draw_mixed_text(draw, card1_x + card_w//2, card_y + 280, "⭐ ⭐ ⭐ ⭐ ⭐ 100% Authentic Bangladeshi Taste", get_font("segoeuib.ttf", 21), 21, (255, 215, 0), anchor="mm")
    draw.text((card1_x + card_w//2, card_y + 355), "Fresh Farm Ingredients • No Artificial Additives", font=get_font("segoeui.ttf", 18), fill=TEXT_MUTED, anchor="mm")

    # Right Card: Call To Action
    card2_x = 680
    draw_rounded_rect(draw, (card2_x, card_y, card2_x + card_w, card_y + card_h), 28, (20, 18, 15, 240), outline=(46, 204, 113, 230), width=2)

    draw.text((card2_x + card_w//2, card_y + 70), "ORDER ONLINE TODAY", font=get_font("arialbd.ttf", 34), fill=ACCENT_GREEN, anchor="mm")
    
    btn_y = card_y + 130
    draw_rounded_rect(draw, (card2_x + 50, btn_y, card2_x + card_w - 50, btn_y + 75), 24, ACCENT_GOLD)
    draw_mixed_text(draw, card2_x + card_w//2, btn_y + 38, "🌐 www.pickpickles.xyz", get_font("arialbd.ttf", 28), 28, (20, 15, 10), anchor="mm")

    draw_mixed_text(draw, card2_x + card_w//2, card_y + 270, "🚚 Cash on Delivery Across Bangladesh", get_font("segoeuib.ttf", 22), 22, TEXT_WHITE, anchor="mm")
    draw_mixed_text(draw, card2_x + card_w//2, card_y + 325, "📦 Fresh Small Batches • Safe Packaging", get_font("segoeui.ttf", 20), 20, TEXT_MUTED, anchor="mm")

    pulse_alpha = int(200 + 55 * math.sin(progress * 12))
    draw_mixed_text(draw, card2_x + card_w//2, card_y + 400, "LIMITED BATCH AVAILABLE • ORDER NOW 🛒", get_font("arialbd.ttf", 21), 21, (255, 200, 80, pulse_alpha), anchor="mm")

    frame = Image.alpha_composite(frame, overlay).convert("RGB")
    return frame

def generate_dynamic_music(total_duration_sec):
    sample_rate = 44100
    t = np.linspace(0, total_duration_sec, int(sample_rate * total_duration_sec), endpoint=False)
    bpm = 118
    beat_dur = 60.0 / bpm
    total_beats = int(total_duration_sec / beat_dur)

    audio = np.zeros(len(t))

    # Drums
    for beat in range(total_beats):
        b_time = beat * beat_dur
        # Kick
        if beat % 2 == 0:
            idx = int(b_time * sample_rate)
            k_dur = int(0.18 * sample_rate)
            if idx + k_dur < len(audio):
                kt = np.linspace(0, 0.18, k_dur)
                k_env = np.exp(-kt * 28)
                k_freq = 140 * np.exp(-kt * 35) + 48
                audio[idx:idx+k_dur] += np.sin(2 * np.pi * k_freq * kt) * k_env * 0.75
        
        # Snare / Clap
        if beat % 2 == 1:
            idx = int(b_time * sample_rate)
            s_dur = int(0.15 * sample_rate)
            if idx + s_dur < len(audio):
                st = np.linspace(0, 0.15, s_dur)
                s_env = np.exp(-st * 22)
                noise = np.random.uniform(-1, 1, s_dur) * s_env * 0.35
                tone = np.sin(2 * np.pi * 210 * st) * s_env * 0.25
                audio[idx:idx+s_dur] += (noise + tone)
                
        # Hi-hat
        for sub in [0, 0.5]:
            h_time = (beat + sub) * beat_dur
            idx = int(h_time * sample_rate)
            h_dur = int(0.04 * sample_rate)
            if idx + h_dur < len(audio):
                ht = np.linspace(0, 0.04, h_dur)
                h_env = np.exp(-ht * 80)
                audio[idx:idx+h_dur] += np.random.uniform(-1, 1, h_dur) * h_env * 0.12

    # Chord progression (C -> Am -> F -> G)
    chord_freqs = [
        [261.63, 329.63, 392.00, 493.88],
        [220.00, 261.63, 329.63, 392.00],
        [174.61, 220.00, 261.63, 329.63],
        [196.00, 246.94, 293.66, 392.00],
    ]
    bass_notes = [65.41, 55.00, 43.65, 49.00]

    prog_len = 4 * 4 * beat_dur
    total_progressions = int(np.ceil(total_duration_sec / prog_len))

    for p in range(total_progressions):
        for i, b_freq in enumerate(bass_notes):
            c_start = (p * 16 + i * 4) * beat_dur
            c_len = 4 * beat_dur
            c_idx = int(c_start * sample_rate)
            c_samples = int(c_len * sample_rate)
            if c_idx < len(audio):
                valid_samples = min(c_samples, len(audio) - c_idx)
                ct = np.linspace(0, valid_samples / sample_rate, valid_samples)
                bass = np.sin(2 * np.pi * b_freq * ct) * 0.35 + np.sin(2 * np.pi * b_freq * 2 * ct) * 0.15
                chords = np.zeros(valid_samples)
                for cf in chord_freqs[i % len(chord_freqs)]:
                    for st_i in range(4):
                        st_t0 = st_i * beat_dur
                        st_idx0 = int(st_t0 * sample_rate)
                        st_dur = int(0.9 * beat_dur * sample_rate)
                        if st_idx0 < valid_samples:
                            sub_len = min(st_dur, valid_samples - st_idx0)
                            sub_t = np.linspace(0, sub_len / sample_rate, sub_len)
                            env = np.exp(-sub_t * 3.5)
                            chords[st_idx0:st_idx0+sub_len] += np.sin(2 * np.pi * cf * sub_t) * env * 0.08
                audio[c_idx:c_idx+valid_samples] += (bass + chords)

    # Fade in & out
    fade_in = int(0.5 * sample_rate)
    fade_out = int(1.5 * sample_rate)
    audio[:fade_in] *= np.linspace(0, 1, fade_in)
    audio[-fade_out:] *= np.linspace(1, 0, fade_out)

    # Normalize
    audio = audio / (np.max(np.abs(audio)) + 1e-5) * 0.88
    wav.write(TEMP_AUDIO, sample_rate, (audio * 32767).astype(np.int16))
    print(f"Generated dynamic music track: {TEMP_AUDIO} ({total_duration_sec:.1f}s)")

def main():
    print(f"Starting 16:9 Video Rendering ({WIDTH}x{HEIGHT} @ {FPS}fps)...")
    fourcc = cv2.VideoWriter_fourcc(*'mp4v')
    out = cv2.VideoWriter(TEMP_VIDEO, fourcc, FPS, (WIDTH, HEIGHT))

    if not out.isOpened():
        print("Error: Could not open VideoWriter.")
        return

    PRODUCT_FRAMES = int(FPS * 2.0)
    OUTRO_FRAMES = int(FPS * 3.0)
    TRANSITION_FRAMES = int(FPS * 0.4)

    total_frames = (len(PRODUCTS) * PRODUCT_FRAMES) + OUTRO_FRAMES
    total_duration = total_frames / FPS
    print(f"Total duration: {total_duration:.1f} seconds ({total_frames} frames)")

    def pil_to_cv2(pil_img):
        return cv2.cvtColor(np.array(pil_img), cv2.COLOR_RGB2BGR)

    last_frame_bgr = None
    current_frame = 0

    # 1. PRODUCTS (Starts directly from first frame)
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
    print("Rendering 16:9 Outro Scene...")
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
    print(f"Video track rendered: {TEMP_VIDEO}")

    # Generate synchronized audio track
    generate_dynamic_music(total_duration)

    # Merge Video & Audio with ffmpeg
    ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()
    print(f"Merging Video & Audio using FFMPEG: {ffmpeg_exe}...")

    cmd = [
        ffmpeg_exe,
        "-y",
        "-i", TEMP_VIDEO,
        "-i", TEMP_AUDIO,
        "-c:v", "libx264",
        "-pix_fmt", "yuv420p",
        "-c:a", "aac",
        "-b:a", "192k",
        "-shortest",
        FINAL_OUTPUT_FILE
    ]

    subprocess.run(cmd, check=True)
    print(f"FINAL VIDEO READY: {FINAL_OUTPUT_FILE}")

    # Cleanup temporary files
    if os.path.exists(TEMP_VIDEO):
        os.remove(TEMP_VIDEO)
    if os.path.exists(TEMP_AUDIO):
        os.remove(TEMP_AUDIO)

if __name__ == "__main__":
    main()

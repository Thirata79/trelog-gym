"""
ジムトレーナー版 トレログ リッチメニュー画像生成
2500x1686px の4ボタンレイアウト
"""
from PIL import Image, ImageDraw, ImageFont
import os

# キャンバスサイズ（LINE推奨）
W, H = 2500, 1686
BG_COLOR = (41, 128, 185)  # ブルー系（ジムらしいカラー）
LINE_COLOR = (255, 255, 255, 80)
TEXT_COLOR = (255, 255, 255)
ICON_BG = (255, 255, 255)
ICON_FG = (41, 128, 185)

# ボタン定義
BUTTONS = [
    {"ja": "記録", "en": "Record", "icon": "pencil"},
    {"ja": "クライアントに送信", "en": "Send to Client", "icon": "send"},
    {"ja": "次回準備", "en": "Next Session", "icon": "menu"},
    {"ja": "レポート確認", "en": "View Report", "icon": "chart"},
]

def find_ja_font(size):
    """日本語フォントを探す"""
    font_paths = [
        "/usr/share/fonts/truetype/droid/DroidSansFallbackFull.ttf",
        "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    ]
    for p in font_paths:
        if os.path.exists(p):
            try:
                return ImageFont.truetype(p, size)
            except Exception:
                continue
    return ImageFont.load_default()

def find_en_font(size):
    """英語フォントを探す"""
    font_paths = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    ]
    for p in font_paths:
        if os.path.exists(p):
            try:
                return ImageFont.truetype(p, size)
            except Exception:
                continue
    return ImageFont.load_default()

def draw_icon(draw, cx, cy, radius, icon_type):
    """アイコン描画"""
    # 白い円
    draw.ellipse(
        [cx - radius, cy - radius, cx + radius, cy + radius],
        fill=ICON_BG
    )

    r = radius * 0.45
    if icon_type == "pencil":
        # ペンアイコン
        draw.line([cx - r, cy + r, cx + r, cy - r], fill=ICON_FG, width=max(3, int(r * 0.3)))
        draw.line([cx - r * 0.8, cy + r * 1.1, cx - r, cy + r], fill=ICON_FG, width=max(3, int(r * 0.3)))
    elif icon_type == "send":
        # 送信アイコン（三角形）
        points = [
            (cx - r, cy - r * 0.8),
            (cx + r, cy),
            (cx - r, cy + r * 0.8),
        ]
        draw.polygon(points, fill=ICON_FG)
    elif icon_type == "menu":
        # メニューアイコン（3本線）
        for i in range(-1, 2):
            y = cy + i * r * 0.7
            draw.line([cx - r, y, cx + r, y], fill=ICON_FG, width=max(3, int(r * 0.25)))
    elif icon_type == "chart":
        # チャートアイコン（棒グラフ）
        bar_w = r * 0.35
        bars = [
            (cx - r * 0.6, cy + r * 0.3, r * 0.8),
            (cx, cy - r * 0.2, r * 1.3),
            (cx + r * 0.6, cy + r * 0.1, r * 1.0),
        ]
        for bx, by, bh in bars:
            draw.rectangle([bx - bar_w / 2, by, bx + bar_w / 2, cy + r], fill=ICON_FG)

def generate():
    img = Image.new("RGB", (W, H), BG_COLOR)
    draw = ImageDraw.Draw(img)

    # 区切り線
    # 横線
    draw.line([(0, H // 2), (W, H // 2)], fill=(255, 255, 255), width=2)
    # 縦線
    draw.line([(W // 2, 0), (W // 2, H)], fill=(255, 255, 255), width=2)

    font_ja = find_ja_font(72)
    font_en = find_en_font(36)

    positions = [
        (W // 4, H // 4),       # 左上
        (3 * W // 4, H // 4),   # 右上
        (W // 4, 3 * H // 4),   # 左下
        (3 * W // 4, 3 * H // 4),  # 右下
    ]

    icon_radius = 45

    for i, btn in enumerate(BUTTONS):
        cx, cy = positions[i]

        # アイコン
        draw_icon(draw, cx, cy - 80, icon_radius, btn["icon"])

        # 日本語テキスト
        ja_text = btn["ja"]
        ja_bbox = draw.textbbox((0, 0), ja_text, font=font_ja)
        ja_w = ja_bbox[2] - ja_bbox[0]
        draw.text((cx - ja_w // 2, cy + 10), ja_text, fill=TEXT_COLOR, font=font_ja)

        # 英語テキスト
        en_text = btn["en"]
        en_bbox = draw.textbbox((0, 0), en_text, font=font_en)
        en_w = en_bbox[2] - en_bbox[0]
        draw.text((cx - en_w // 2, cy + 95), en_text, fill=(255, 255, 255, 180), font=font_en)

    output_path = os.path.join(os.path.dirname(__file__), "richmenu.png")
    img.save(output_path)
    print(f"リッチメニュー画像を生成しました: {output_path}")
    return output_path

if __name__ == "__main__":
    generate()

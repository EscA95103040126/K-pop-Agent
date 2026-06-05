from __future__ import annotations

import argparse
import tempfile
from pathlib import Path

import requests
from dotenv import load_dotenv
from PIL import Image, ImageDraw, ImageFont


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_IMAGE_PATH = PROJECT_ROOT / "data" / "rich_menu.png"
RICH_MENU_SIZE = (2500, 1686)
BACKGROUND_COLOR = "#FAF7F4"
DIVIDER_COLOR = "#E8D5C4"
TEXT_COLOR = "#8B5E52"
LINE_API_BASE = "https://api.line.me/v2/bot"
LINE_DATA_API_BASE = "https://api-data.line.me/v2/bot"
EMOJI_FONT_PATH = "/System/Library/Fonts/Apple Color Emoji.ttc"
RICH_MENU_ITEMS = [
    {"column": 0, "row": 0, "icon": "🔍", "label": "分析藝人", "action_text": "選擇藝人"},
    {"column": 1, "row": 0, "icon": "📊", "label": "本週榜單", "action_text": "本週 K-pop 榜單"},
    {"column": 2, "row": 0, "icon": "🎮", "label": "互動專區", "action_text": "互動專區"},
    {"column": 0, "row": 1, "icon": "🎧", "label": "每日一首", "action_text": "每日一首"},
    {"column": 1, "row": 1, "icon": "🧭", "label": "AI 入坑", "action_text": "AI 入坑"},
    {"column": 2, "row": 1, "icon": "⭐", "label": "我的口袋", "action_text": "我的口袋"},
]


def main() -> None:
    parser = argparse.ArgumentParser(description="Create and set the default LINE rich menu.")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Generate the rich menu image and payload without calling LINE APIs.",
    )
    parser.add_argument(
        "--image",
        type=Path,
        default=None,
        help=(
            "Path to a custom rich menu PNG. "
            f"Defaults to {DEFAULT_IMAGE_PATH} if it exists, "
            "otherwise generates the image programmatically."
        ),
    )
    args = parser.parse_args()

    load_dotenv(PROJECT_ROOT / ".env")
    token = _line_access_token()
    image_path = _resolve_image(args.image)
    payload = _rich_menu_payload()

    if args.dry_run:
        print(f"Dry run OK. Image: {image_path}")
        print(f"Rich menu name: {payload['name']}")
        return

    if not token:
        raise RuntimeError("LINE_CHANNEL_ACCESS_TOKEN is required in .env")

    rich_menu_id = _create_rich_menu(token, payload)
    _upload_rich_menu_image(token, rich_menu_id, image_path)
    _set_default_rich_menu(token, rich_menu_id)
    print(f"Default rich menu set: {rich_menu_id}")


def _resolve_image(custom_path: Path | None) -> Path:
    """Return the image to upload. Priority: --image arg > data/rich_menu.png > generated."""
    if custom_path is not None:
        if not custom_path.exists():
            raise FileNotFoundError(f"Custom image not found: {custom_path}")
        return _ensure_line_size(custom_path)
    if DEFAULT_IMAGE_PATH.exists():
        print(f"Using custom image: {DEFAULT_IMAGE_PATH}")
        return _ensure_line_size(DEFAULT_IMAGE_PATH)
    print("No custom image found — generating image programmatically.")
    return _create_rich_menu_image()


def _ensure_line_size(src: Path) -> Path:
    """Resize image to RICH_MENU_SIZE if needed and return path to a temp PNG."""
    img = Image.open(src).convert("RGB")
    if img.size != RICH_MENU_SIZE:
        print(f"Resizing {img.size} → {RICH_MENU_SIZE}")
        img = img.resize(RICH_MENU_SIZE, Image.LANCZOS)
    output_path = Path(tempfile.gettempdir()) / "kpop_agent_rich_menu.png"
    img.save(output_path, "PNG")
    return output_path


def _line_access_token() -> str:
    from os import getenv

    return getenv("LINE_CHANNEL_ACCESS_TOKEN", "").strip()


def _rich_menu_payload() -> dict:
    button_width = RICH_MENU_SIZE[0] // 3
    button_height = RICH_MENU_SIZE[1] // 2
    return {
        "size": {"width": RICH_MENU_SIZE[0], "height": RICH_MENU_SIZE[1]},
        "selected": True,
        "name": "K-pop Agent Rich Menu",
        "chatBarText": "功能選單",
        "areas": [
            _rich_menu_area(
                item["column"],
                item["row"],
                item["action_text"],
                button_width,
                button_height,
            )
            for item in RICH_MENU_ITEMS
        ],
    }


def _rich_menu_area(
    column: int,
    row: int,
    text: str,
    button_width: int,
    button_height: int,
) -> dict:
    x = button_width * column
    y = button_height * row
    width = RICH_MENU_SIZE[0] - x if column == 2 else button_width
    height = RICH_MENU_SIZE[1] - y if row == 1 else button_height
    return {
        "bounds": {"x": x, "y": y, "width": width, "height": height},
        "action": {"type": "message", "text": text},
    }


def _create_rich_menu_image() -> Path:
    image = Image.new("RGB", RICH_MENU_SIZE, BACKGROUND_COLOR)
    draw = ImageDraw.Draw(image)
    emoji_font = _load_emoji_font(74)
    title_font = _load_text_font(58)
    button_width = RICH_MENU_SIZE[0] // 3
    button_height = RICH_MENU_SIZE[1] // 2

    for item in RICH_MENU_ITEMS:
        column = int(item["column"])
        row = int(item["row"])
        x0 = button_width * column
        y0 = button_height * row
        x1 = RICH_MENU_SIZE[0] if column == 2 else button_width * (column + 1)
        y1 = RICH_MENU_SIZE[1] if row == 1 else button_height * (row + 1)
        center_x = (x0 + x1) // 2
        if column > 0:
            draw.line((x0, y0 + 90, x0, y1 - 90), fill=DIVIDER_COLOR, width=5)
        if row > 0:
            draw.line((x0 + 90, y0, x1 - 90, y0), fill=DIVIDER_COLOR, width=5)

        _draw_centered_text(draw, item["icon"], center_x, y0 + 220, emoji_font)
        _draw_centered_text(draw, item["label"], center_x, y0 + 420, title_font)

    output_path = Path(tempfile.gettempdir()) / "kpop_agent_rich_menu.png"
    image.save(output_path, "PNG")
    return output_path


def _load_emoji_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    if Path(EMOJI_FONT_PATH).exists():
        for candidate_size in (size, 160, 128, 109, 96, 80, 64, 48, 32):
            try:
                return ImageFont.truetype(EMOJI_FONT_PATH, size=candidate_size)
            except OSError:
                continue
    return ImageFont.load_default()


def _load_text_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    candidates = [
        "/System/Library/Fonts/STHeiti Medium.ttc",
        "/System/Library/Fonts/PingFang.ttc",
        "/System/Library/Fonts/Supplemental/Songti.ttc",
        "/System/Library/Fonts/Supplemental/AppleGothic.ttf",
        "/Library/Fonts/Arial Unicode.ttf",
    ]
    for candidate in candidates:
        if Path(candidate).exists():
            return ImageFont.truetype(candidate, size=size)
    return ImageFont.load_default()


def _draw_centered_text(
    draw: ImageDraw.ImageDraw,
    text: str,
    center_x: int,
    y: int,
    font: ImageFont.FreeTypeFont | ImageFont.ImageFont,
) -> None:
    bbox = draw.textbbox((0, 0), text, font=font)
    width = bbox[2] - bbox[0]
    draw.text((center_x - width / 2, y), text, fill=TEXT_COLOR, font=font)


def _create_rich_menu(token: str, payload: dict) -> str:
    response = requests.post(
        f"{LINE_API_BASE}/richmenu",
        headers=_json_headers(token),
        json=payload,
        timeout=15,
    )
    response.raise_for_status()
    return response.json()["richMenuId"]


def _upload_rich_menu_image(token: str, rich_menu_id: str, image_path: Path) -> None:
    response = requests.post(
        f"{LINE_DATA_API_BASE}/richmenu/{rich_menu_id}/content",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "image/png"},
        data=image_path.read_bytes(),
        timeout=20,
    )
    response.raise_for_status()


def _set_default_rich_menu(token: str, rich_menu_id: str) -> None:
    response = requests.post(
        f"{LINE_API_BASE}/user/all/richmenu/{rich_menu_id}",
        headers=_json_headers(token),
        timeout=15,
    )
    response.raise_for_status()


def _json_headers(token: str) -> dict:
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }


if __name__ == "__main__":
    main()

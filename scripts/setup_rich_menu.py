from __future__ import annotations

import argparse
import tempfile
from pathlib import Path

import requests
from dotenv import load_dotenv
from PIL import Image, ImageDraw, ImageFont


PROJECT_ROOT = Path(__file__).resolve().parents[1]
RICH_MENU_SIZE = (2500, 843)
BACKGROUND_COLOR = "#1E1E1E"
TEXT_COLOR = "#FFFFFF"
LINE_API_BASE = "https://api.line.me/v2/bot"
LINE_DATA_API_BASE = "https://api-data.line.me/v2/bot"


def main() -> None:
    parser = argparse.ArgumentParser(description="Create and set the default LINE rich menu.")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Generate the rich menu image and payload without calling LINE APIs.",
    )
    args = parser.parse_args()

    load_dotenv(PROJECT_ROOT / ".env")
    token = _line_access_token()
    image_path = _create_rich_menu_image()
    payload = _rich_menu_payload()

    if args.dry_run:
        print(f"Dry run OK. Generated image: {image_path}")
        print(f"Rich menu name: {payload['name']}")
        return

    if not token:
        raise RuntimeError("LINE_CHANNEL_ACCESS_TOKEN is required in .env")

    rich_menu_id = _create_rich_menu(token, payload)
    _upload_rich_menu_image(token, rich_menu_id, image_path)
    _set_default_rich_menu(token, rich_menu_id)
    print(f"Default rich menu set: {rich_menu_id}")


def _line_access_token() -> str:
    from os import getenv

    return getenv("LINE_CHANNEL_ACCESS_TOKEN", "").strip()


def _rich_menu_payload() -> dict:
    button_width = RICH_MENU_SIZE[0] // 3
    return {
        "size": {"width": RICH_MENU_SIZE[0], "height": RICH_MENU_SIZE[1]},
        "selected": True,
        "name": "K-pop Agent Rich Menu",
        "chatBarText": "K-pop Agent",
        "areas": [
            {
                "bounds": {"x": 0, "y": 0, "width": button_width, "height": RICH_MENU_SIZE[1]},
                "action": {"type": "message", "text": "分析 "},
            },
            {
                "bounds": {
                    "x": button_width,
                    "y": 0,
                    "width": button_width,
                    "height": RICH_MENU_SIZE[1],
                },
                "action": {"type": "message", "text": "本週 K-pop 榜單"},
            },
            {
                "bounds": {
                    "x": button_width * 2,
                    "y": 0,
                    "width": RICH_MENU_SIZE[0] - button_width * 2,
                    "height": RICH_MENU_SIZE[1],
                },
                "action": {"type": "message", "text": "使用說明"},
            },
        ],
    }


def _create_rich_menu_image() -> Path:
    image = Image.new("RGB", RICH_MENU_SIZE, BACKGROUND_COLOR)
    draw = ImageDraw.Draw(image)
    font = _load_font(78)
    sub_font = _load_font(36)
    labels = [
        ("🔍", "分析藝人", "分析 "),
        ("📊", "本週榜單", "本週 K-pop 榜單"),
        ("ℹ️", "使用說明", "使用說明"),
    ]
    button_width = RICH_MENU_SIZE[0] // 3

    for index, (icon, title, subtitle) in enumerate(labels):
        x0 = button_width * index
        x1 = RICH_MENU_SIZE[0] if index == 2 else button_width * (index + 1)
        center_x = (x0 + x1) // 2
        if index > 0:
            draw.line((x0, 90, x0, RICH_MENU_SIZE[1] - 90), fill="#3A3A3A", width=4)

        title_text = f"{icon} {title}"
        _draw_centered_text(draw, title_text, center_x, 330, font)
        _draw_centered_text(draw, subtitle, center_x, 450, sub_font)

    output_path = Path(tempfile.gettempdir()) / "kpop_agent_rich_menu.png"
    image.save(output_path, "PNG")
    return output_path


def _load_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    candidates = [
        "/System/Library/Fonts/PingFang.ttc",
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

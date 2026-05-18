from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.tools.sentiment import load_comments, get_comments_by_artist


def main():
    comments = load_comments()

    print(f"total: {len(comments)}")

    if comments:
        print(f"columns: {list(comments[0].keys())}")
    else:
        print("columns: []")

    for artist in ["aespa", "IVE", "NewJeans", "new jeans", "Unknown"]:
        artist_comments = get_comments_by_artist(artist)
        print(f"{artist} comments: {len(artist_comments)}")


if __name__ == "__main__":
    main()

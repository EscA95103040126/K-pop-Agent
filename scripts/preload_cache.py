from __future__ import annotations

import sys
import time
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.agent import DEMO_ARTISTS, KpopAnalysisAgent, artist_cache_path


def main() -> None:
    agent = KpopAnalysisAgent()
    success_count = 0
    failed: list[tuple[str, str]] = []

    for index, artist in enumerate(DEMO_ARTISTS):
        try:
            payload = agent.preload_artist_cache(artist)
            success_count += 1
            print(
                f"OK {artist}: {artist_cache_path(artist)} "
                f"(cached_at={payload['cached_at']})"
            )
        except Exception as exc:
            failed.append((artist, str(exc)))
            print(f"FAILED {artist}: {exc}")

        if index < len(DEMO_ARTISTS) - 1:
            time.sleep(2)

    print(f"Preloaded artist caches: {success_count}/{len(DEMO_ARTISTS)}")
    if failed:
        print("Failures:")
        for artist, error in failed:
            print(f"- {artist}: {error}")


if __name__ == "__main__":
    main()

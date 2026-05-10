from pathlib import Path
import gzip
import json
import time
import argparse
import requests

BASE_DIR = Path(__file__).resolve().parent
POSTER_DIR = BASE_DIR / "posters"
POSTER_DIR.mkdir(exist_ok=True)

MOVIES_FILE = BASE_DIR / "movies.json.gz"
CHECKPOINT_FILE = BASE_DIR / "poster_cache_checkpoint.json"

#OMDB_API_KEY = "ac11a76"
OMDB_API_KEY = "80b0d7b7"


def load_checkpoint():
    if CHECKPOINT_FILE.exists():
        try:
            with open(CHECKPOINT_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass

    return {"last_index": 0}


def save_checkpoint(index):
    with open(CHECKPOINT_FILE, "w", encoding="utf-8") as f:
        json.dump({"last_index": index}, f)


def votes_number(movie):
    try:
        return int(movie.get("votes") or 0)
    except ValueError:
        return 0


def fetch_poster(tconst):
    poster_path = POSTER_DIR / f"{tconst}.jpg"
    missing_path = POSTER_DIR / f"{tconst}.missing"

    if poster_path.exists() or missing_path.exists():
        return "cached"

    try:
        omdb_url = f"https://www.omdbapi.com/?i={tconst}&apikey={OMDB_API_KEY}"
        omdb = requests.get(omdb_url, timeout=8).json()

        poster_url = omdb.get("Poster")

        if not poster_url or poster_url == "N/A":
            missing_path.write_text("missing", encoding="utf-8")
            return "missing"

        img = requests.get(poster_url, timeout=12)

        if img.status_code != 200:
            missing_path.write_text("missing", encoding="utf-8")
            return "failed"

        poster_path.write_bytes(img.content)
        return "saved"

    except Exception as e:
        return f"error: {e}"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=500)
    parser.add_argument("--delay", type=float, default=0.3)
    parser.add_argument("--query", type=str, default="")
    parser.add_argument("--reset", action="store_true")
    args = parser.parse_args()

    with gzip.open(MOVIES_FILE, "rt", encoding="utf-8") as f:
        movies = json.load(f)

    if args.query:
        q = args.query.lower()
        movies = [
            m for m in movies
            if q in (m.get("title") or "").lower()
            or q in (m.get("originalTitle") or "").lower()
            or q in (m.get("id") or "").lower()
        ]

    movies.sort(key=votes_number, reverse=True)

    if args.reset and CHECKPOINT_FILE.exists():
        CHECKPOINT_FILE.unlink()

    checkpoint = load_checkpoint()
    start_index = int(checkpoint.get("last_index", 0))

    end_index = min(start_index + args.limit, len(movies))

    print(f"Starting from index: {start_index}")
    print(f"Stopping at index: {end_index}")
    print("Sorted by most reviews/votes first")

    index = start_index

    try:
        for index in range(start_index, end_index):
            movie = movies[index]

            tconst = movie["id"]
            title = movie.get("title", "")
            votes = movie.get("votes", "0")

            result = fetch_poster(tconst)

            print(
                f"{index + 1}/{len(movies)} "
                f"{tconst} | {votes} votes | {title} -> {result}"
            )

            save_checkpoint(index + 1)
            time.sleep(args.delay)

    except KeyboardInterrupt:
        print("\nInterrupted. Checkpoint saved.")
        save_checkpoint(index)
        return

    print("Done. Checkpoint saved.")


if __name__ == "__main__":
    main()
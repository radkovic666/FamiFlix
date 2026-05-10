import csv
import gzip
import json
import urllib.request
from pathlib import Path

DATA_DIR = Path("imdb_data")
OUT_DIR = Path(".")

FILES = {
    "basics": "https://datasets.imdbws.com/title.basics.tsv.gz",
    "ratings": "https://datasets.imdbws.com/title.ratings.tsv.gz",
}

DATA_DIR.mkdir(exist_ok=True)
OUT_DIR.mkdir(exist_ok=True)


def download(url, path):
    if not path.exists():
        print(f"Downloading {url}")
        urllib.request.urlretrieve(url, path)


def read_ratings():
    ratings = {}

    with gzip.open(DATA_DIR / "title.ratings.tsv.gz", "rt", encoding="utf-8") as f:
        reader = csv.DictReader(f, delimiter="\t")
        for row in reader:
            ratings[row["tconst"]] = {
                "rating": row["averageRating"],
                "votes": row["numVotes"],
            }

    return ratings


def build_movies_json():
    ratings = read_ratings()
    movies = []

    with gzip.open(DATA_DIR / "title.basics.tsv.gz", "rt", encoding="utf-8") as f:
        reader = csv.DictReader(f, delimiter="\t")

        for row in reader:
            if row["titleType"] != "movie":
                continue

            if row["runtimeMinutes"] == r"\N":
                continue

            try:
                runtime = int(row["runtimeMinutes"])
            except ValueError:
                continue

            if runtime < 40:
                continue

            tconst = row["tconst"]

            movies.append({
                "id": tconst,
                "title": row["primaryTitle"],
                "originalTitle": row["originalTitle"],
                "year": row["startYear"],
                "runtime": row["runtimeMinutes"],
                "genres": row["genres"],
                "rating": ratings.get(tconst, {}).get("rating", ""),
                "votes": ratings.get(tconst, {}).get("votes", ""),
                "playUrl": f"https://streamimdb.me/embed/movie/{tconst}/",
                "imdbUrl": f"https://www.imdb.com/title/{tconst}/",
            })

    with open(OUT_DIR / "movies.json", "w", encoding="utf-8") as f:
        json.dump(movies, f, ensure_ascii=False)

    print(f"Saved {len(movies)} movies")


def build_html():
    html = """<!DOCTYPE html>
<html>
<head>
  <meta charset="UTF-8">
  <title>IMDb Feature Movies</title>
  <style>
    body {
      font-family: Arial, sans-serif;
      background: #111;
      color: #eee;
      margin: 0;
      padding: 20px;
    }

    h1 {
      color: #f5c518;
    }

    input {
      width: 100%;
      padding: 14px;
      font-size: 18px;
      margin-bottom: 10px;
      border-radius: 8px;
      border: none;
    }

    .note {
      color: #aaa;
      margin-bottom: 20px;
    }

    .grid {
      display: grid;
      grid-template-columns: repeat(auto-fill, minmax(180px, 1fr));
      gap: 18px;
    }

    .card {
      background: #1c1c1c;
      border-radius: 10px;
      overflow: hidden;
      cursor: pointer;
    }

    .card:hover {
      transform: scale(1.03);
    }

    .poster {
      width: 100%;
      height: 270px;
      object-fit: cover;
      background: #333;
    }

    .placeholder {
      width: 100%;
      height: 270px;
      background: #333;
      display: flex;
      align-items: center;
      justify-content: center;
      color: #888;
      text-align: center;
      padding: 10px;
      box-sizing: border-box;
    }

    .info {
      padding: 10px;
    }

    .title {
      font-weight: bold;
      color: white;
    }

    .meta {
      color: #aaa;
      font-size: 14px;
      margin-top: 5px;
    }

    button {
      margin: 20px auto;
      display: block;
      padding: 12px 30px;
      font-size: 16px;
      cursor: pointer;
    }
  </style>
</head>
<body>

<h1>IMDb Feature Movies</h1>

<input id="search" placeholder="Search movie title, e.g. Taxi 2">
<div class="note">
  Posters are fetched only for visible search results to protect your OMDb daily limit.
</div>

<div id="count"></div>
<div class="grid" id="movies"></div>
<button id="loadMore">Load more</button>

<script>
const OMDB_API_KEY = "80b0d7b7";
const PAGE_SIZE = 40;
const POSTER_FETCH_LIMIT_PER_SEARCH = 20;

let allMovies = [];
let filteredMovies = [];
let visible = 0;
let posterCache = JSON.parse(localStorage.getItem("posterCache") || "{}");

const grid = document.getElementById("movies");
const search = document.getElementById("search");
const count = document.getElementById("count");
const loadMore = document.getElementById("loadMore");

function savePosterCache() {
  localStorage.setItem("posterCache", JSON.stringify(posterCache));
}

async function fetchPoster(movie, imgElement, placeholderElement) {
  if (posterCache[movie.id]) {
    if (posterCache[movie.id] !== "N/A") {
      imgElement.src = posterCache[movie.id];
      imgElement.style.display = "block";
      placeholderElement.style.display = "none";
    }
    return;
  }

  try {
    const url = `https://www.omdbapi.com/?i=${movie.id}&apikey=${OMDB_API_KEY}`;
    const res = await fetch(url);
    const data = await res.json();

    const poster = data.Poster && data.Poster !== "N/A" ? data.Poster : "N/A";
    posterCache[movie.id] = poster;
    savePosterCache();

    if (poster !== "N/A") {
      imgElement.src = poster;
      imgElement.style.display = "block";
      placeholderElement.style.display = "none";
    }
  } catch (e) {
    console.warn("Poster fetch failed", movie.id);
  }
}

function render(reset = false) {
  if (reset) {
    grid.innerHTML = "";
    visible = 0;
  }

  const next = filteredMovies.slice(visible, visible + PAGE_SIZE);
  let posterFetches = 0;

  for (const movie of next) {
    const card = document.createElement("div");
    card.className = "card";

    card.onclick = () => {
      window.open(movie.playUrl, "_blank");
    };

    card.innerHTML = `
      <img class="poster" style="display:none" loading="lazy">
      <div class="placeholder">No poster loaded</div>
      <div class="info">
        <div class="title">${escapeHtml(movie.title)}</div>
        <div class="meta">${movie.year || "Unknown"} • ${movie.runtime} min</div>
        <div class="meta">${movie.genres || ""}</div>
        <div class="meta">⭐ ${movie.rating || "N/A"} (${movie.votes || 0} votes)</div>
        <div class="meta">${movie.id}</div>
      </div>
    `;

    grid.appendChild(card);

    const img = card.querySelector(".poster");
    const placeholder = card.querySelector(".placeholder");

    if (posterFetches < POSTER_FETCH_LIMIT_PER_SEARCH) {
      posterFetches++;
      fetchPoster(movie, img, placeholder);
    }
  }

  visible += next.length;
  count.textContent = `Showing ${Math.min(visible, filteredMovies.length)} of ${filteredMovies.length} movies`;
  loadMore.style.display = visible >= filteredMovies.length ? "none" : "block";
}

function escapeHtml(text) {
  return String(text).replace(/[&<>"']/g, function(m) {
    return ({
      "&": "&amp;",
      "<": "&lt;",
      ">": "&gt;",
      '"': "&quot;",
      "'": "&#039;"
    })[m];
  });
}

search.addEventListener("input", () => {
  const q = search.value.toLowerCase().trim();

  if (!q) {
    filteredMovies = allMovies.slice(0, 1000);
  } else {
    filteredMovies = allMovies.filter(movie =>
      movie.title.toLowerCase().includes(q) ||
      movie.originalTitle.toLowerCase().includes(q) ||
      movie.id.toLowerCase().includes(q)
    );
  }

  render(true);
});

loadMore.addEventListener("click", () => render());

fetch("movies.json")
  .then(res => res.json())
  .then(data => {
    allMovies = data;

    // Default view: only first 1000, to avoid rendering 600k cards
    filteredMovies = allMovies.slice(0, 1000);

    render(true);
  });
</script>

</body>
</html>
"""

    with open(OUT_DIR / "index.html", "w", encoding="utf-8") as f:
        f.write(html)

    print("Saved site/index.html")


if __name__ == "__main__":
    download(FILES["basics"], DATA_DIR / "title.basics.tsv.gz")
    download(FILES["ratings"], DATA_DIR / "title.ratings.tsv.gz")

    build_movies_json()
    build_html()

    print("Done. Open site/index.html")
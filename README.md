# FamiFlix

FamiFlix is a lightweight FastAPI service and static site generator for browsing IMDb-based movie and TV series catalogs.

## Features

- Serves poster images and catalog metadata through a FastAPI backend.
- Loads movie/series data from `movies.json(.gz)` and `series.json(.gz)` files.
- Provides filtering, sorting, and search over titles.
- Includes helper scripts for building catalog JSON and caching posters.

## Project Files

- `server.py` — main API server.
- `assets/styles.css` — frontend styles.
- `assets/app.js` — frontend behavior.
- `run_famiflix.sh` — one-command start script (plug-and-play).
- `famiflix.service` — Linux systemd service template.
- `build_imdb_movies_site.py` / `build_imdb_series_site.py` — build catalog data.
- `cacheposters.py` / `cacheseries.py` — cache poster assets.
- `index.html` — frontend entry page.

## Requirements

Install dependencies:

```bash
pip install -r requirements.txt
```

## Run the project (plug-and-play)

```bash
./run_famiflix.sh
```

Then open:

- API docs: `http://localhost:5050/docs`
- Frontend: `http://localhost:5050/`

## Linux service (systemd)

1. Copy project to `/var/www/FamiFlix`.
2. Copy the service file:

```bash
sudo cp famiflix.service /etc/systemd/system/famiflix.service
```

3. Enable and start:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now famiflix.service
```

4. Check status/logs:

```bash
sudo systemctl status famiflix.service
sudo journalctl -u famiflix.service -f
```

## Environment Variables

- `OMDB_API_KEY` — OMDb API key used for metadata lookups (optional; default is set in code).

## Notes

- Ensure catalog files exist (`movies.json`/`movies.json.gz` and `series.json`/`series.json.gz`) before starting the app.

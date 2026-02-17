# Schedule front-end (temporary)

Minimal UI to view schedule: events (rings) → classes → entries (horse, rider). Click a row to expand and see **class details**, **horse details**, and **entry/status** from the backend DB.

## Run

1. Start the FastAPI backend (from project root):
   ```bash
   uvicorn app.main:app --reload
   ```
2. Open `index.html` in a browser:
   - Either open the file directly: `front-end/index.html`
   - Or serve the folder (e.g. `python -m http.server 3000` in `front-end`) and go to `http://localhost:3000`

The page uses `API_BASE = 'http://localhost:8000'` by default. If the front-end is served from the same host as the API, set `API_BASE = ''` in the script.

## API

- **GET** `/api/v1/schedule/view?date=YYYY-MM-DD` — returns events with classes and entries (horse, rider, status). Default date is today.

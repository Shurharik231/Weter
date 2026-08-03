# Wind Trajectory

FastAPI + Leaflet application for estimating balloon trajectories using Open-Meteo wind data.

## What is included

- Interactive Leaflet map.
- Forward trajectory calculation with RK4 integration.
- Wind lookup at a selected point and altitude.
- Backtrajectory ensemble endpoint.
- Favorable launch-window search endpoint.
- Open-Meteo forecast/archive data with local interpolation.
- In-memory weather caching.

## Run locally

Create and activate a virtual environment:

```bash
python -m venv .venv
```

Windows PowerShell:

```powershell
.venv\Scripts\Activate.ps1
```

Linux/macOS:

```bash
source .venv/bin/activate
```

Install dependencies:

```bash
python -m pip install -r requirements.txt
```

Start the server:

```bash
uvicorn app:app --reload
```

Open `http://127.0.0.1:8000` in a browser.

## API

- `GET /api/health` — health check.
- `GET /api/wind?lat=52.23&lon=21.01&altitude=1000` — wind at a point.
- `POST /api/trajectory` — forward trajectory.
- `POST /api/backtrajectory` — ensemble backtrajectory.
- `POST /api/favorable` — search for favorable launch windows.
- `GET /api/config` — runtime defaults.
- `GET /docs` — interactive FastAPI documentation.

## Forward trajectory example

```json
{
  "start": {"lat": 52.2297, "lon": 21.0122},
  "start_time": "2026-08-03T12:00:00Z",
  "start_altitude": 0,
  "ascent_rate": 5,
  "max_altitude": 10000,
  "duration_hours": 6,
  "step_minutes": 10
}
```

## Notes

Weather data is provided by Open-Meteo. Network access is required for calculations. The backtrajectory endpoint uses an ensemble and can take noticeably longer than the forward calculation.

This project is a trajectory-estimation tool, not a safety-critical navigation system. Validate weather and model assumptions before real-world use.

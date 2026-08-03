# Wind Trajectory v2

Lightweight FastAPI + Leaflet application for forward trajectory estimation using Open-Meteo.

## Improvements in v2

- Forecast is fetched as a geographic grid around the expected route, not only at the start point.
- Wind is interpolated in four dimensions: time, latitude, longitude and altitude.
- Altitude uses interpolation between pressure levels.
- Forecast is cached in RAM for a short period.
- Wind field arrows are displayed on the map for a selected altitude.
- API errors and forecast limits are handled explicitly.
- The route engine stops when it leaves the available forecast domain.
- 10-minute integration step is kept for speed and simplicity.
- Route statistics and charts remain lightweight.

## Run

bash
python -m venv .venv

# Linux/macOS
source .venv/bin/activate

# Windows
# .venv\Scripts\activate

pip install -r requirements.txt
uvicorn app:app --reload


Open http://127.0.0.1:8000

## Test

Default point:
44.67, 34.41

Try:
- start altitude: 0 m
- ascent rate: 5 m/s
- max altitude: 10000 m
- duration: 6 hours

Click "Рассчитать маршрут".

## Model

Horizontal movement follows the forecast wind. Vertical movement is:

z(t) = min(max_altitude, start_altitude + ascent_rate * t)

The forecast is downloaded once for a compact grid around the expected route. The application then interpolates wind locally.

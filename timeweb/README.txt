WETER — WEB VERSION FOR ORDINARY TIMEWEB PHP 8.2

Upload ONLY the contents of this folder to the site's web directory (for example public_html/weter/).

Open the resulting index.php in a browser.

Requirements:
- PHP 8.2+
- cURL extension enabled
- outbound HTTPS requests allowed to Open-Meteo
- Leaflet/OpenStreetMap access from the visitor's browser

No Python, Composer, Node.js, Uvicorn or server daemon is required.

Implemented from the main FastAPI project:
- direct forward trajectory with pressure-level wind interpolation and RK4 integration;
- reverse/back trajectory with uncertainty ensemble and launch zones;
- favorable launch-window search with launch rings, weather filters, wind shear, precipitation/thunderstorm hazards and ensemble scoring;
- target polygon, restricted zones and hazard zones are supported by the API;
- /?api=health, /?api=config and /?api=wind compatibility endpoints;
- responsive Leaflet web interface for the three main modes.

The ordinary PHP deployment intentionally runs the favorable search synchronously because standard Timeweb PHP hosting does not provide the FastAPI in-process background task worker used by the Python application. The calculation itself remains available through /?api=favorable.

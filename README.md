# Spotter — Weather-Aware Truck Routing

A Django + React app that helps a truck driver choose the safest route. It compares three truck routes against the weather forecast at the time the truck reaches each checkpoint, applies the load-weight wind rules, and recommends a route by balancing weather risk and travel time.

- **Live app:** https://spotter-one-ashy.vercel.app
- **API:** https://spotter-ihwd.onrender.com/api/health/ (free tier: the first request after idle takes about 30 s to wake up)
- **Walkthrough (Loom):** _link coming soon_

---

## What it does

1. **Three truck routes.** OpenRouteService's `driving-hgv` (heavy goods vehicle) profile gives the main route. Alternatives come from ORS's own `alternative_routes` on short trips, and otherwise from detour waypoints to either side of the trip. Each alternative is still truck-routed and is kept only if it is clearly different (no more than 80% of its path shared) and no more than 60% slower than the fastest route.
2. **Checkpoints with real ETAs.** Weather is sampled every 10, 25 or 50 miles. *Auto* picks one interval for all three routes from the longest (10 mi under 100 mi, 25 mi under 500 mi, otherwise 50 mi), and the form can override it. Each checkpoint's ETA comes from the routing engine's per-step durations, so slow city streets and fast interstates keep their real speeds.
3. **Forecast at the ETA.** Open-Meteo hourly wind, rain and snowfall for the hour nearest each checkpoint's ETA, up to Open-Meteo's 16-day range. Departures in the past are rejected, as are trips that would end after the forecast runs out.
4. **Risk per checkpoint** from the threshold table and load rules below. Each checkpoint represents the road halfway to its neighbours, so risk miles add up to the route length.
5. **Recommendation** using the order below.
6. **Map:** routes coloured by risk, checkpoint popups with ETA and weather, and route cards with a risk-mile breakdown and a checkpoint table.
7. **Corridor heatmap with a 0–48 h slider.** About 75–180 forecast points cover the corridor around all three routes. The frontend blends them into a continuous field in which every colour is a risk level. Overall, wind, rain and snow layers are available, plus play/pause.

### Risk rules

| Condition | Low | Moderate | High | Severe | No Travel |
|---|---|---|---|---|---|
| Wind (mph) | < 25 | 25–34 | 35–44 | 45–54 | ≥ 55 |
| Rain (in/hr) | < 0.10 | 0.10–0.25 | 0.25–0.50 | 0.50–1.00 | > 1.00 |
| Snow (in/hr) | < 0.5 | 0.5–1.0 | 1.0–2.0 | 2.0–3.0 | > 3.0 |

Load rules: ≥ 55 mph is No Travel for any load. 45–54 mph with > 30,000 lb is No Travel. 35–44 mph with > 40,000 lb is Severe. A checkpoint's overall risk is the worst of wind, rain and snow. A value exactly on a shared boundary (e.g. 0.25 in/hr rain) takes the higher class.

### Recommendation order

1. Routes with complete weather data rank above routes where some checkpoints are *Unknown* (forecast unavailable). Missing data is never treated as calm weather.
2. Fewest **No Travel** miles
3. Fewest **Severe** miles
4. Fewest **High** miles
5. Lowest **average risk**: mile-weighted, 0 = Low … 4 = No Travel. Differences under **0.25** count as a tie, so travel time decides. Without this, a single 50-mile Moderate stretch (average 0.04 vs 0.00) would make the app recommend a route hours slower.
6. Shortest **travel time**

Steps 2–4 follow the assessment's list exactly. Step 1, ranking No Travel first, and the tolerance in step 5 are deliberate additions.

### Fallbacks and notices

- Without an ORS key, or when ORS is down or out of quota, routing falls back to public OSRM. OSRM only has a car profile, so the UI says that travel times are car estimates. Providers are never mixed, so travel times stay comparable.
- Geocoding uses Nominatim (OpenStreetMap) first and the ORS geocoder second. Results are cached for 24 h, routes for 15 min and forecasts for 30 min.
- **Simulate a storm** replaces the forecast with one synthetic storm that moves along the trip over 48 h. Checkpoints and heatmap sample the same storm, so all five risk levels and the load rules can be demonstrated on a calm day.

---

## Project layout

```
backend/
  spotter/settings.py             env-driven settings (see backend/.env.example)
  routing/
    views.py                      POST /api/routes/, GET /api/health/
    serializers.py                request validation (departure window, interval, weight)
    tests.py                      48 unit and API tests (no network)
    management/commands/smoke_test.py   live end-to-end check against the real APIs
    services/
      route_service.py            geocoding, ORS/OSRM routing, alternatives, ETA checkpoints, names
      weather_service.py          batched Open-Meteo lookups for exact hour windows
      risk_service.py             thresholds, load rules, risk miles
      recommend_service.py        ranking
      corridor_service.py         corridor grid and 0–48 h frames
      simulation_service.py       synthetic storm
      geo.py, errors.py           shared helpers
frontend/src/
  App.jsx                         layout, search request, notices
  components/
    InputForm.jsx                 trip inputs, presets, interval selector (shown in a modal)
    Modal.jsx                     accessible dialog (Esc, backdrop, focus)
    TripSummary.jsx               searched trip with an Edit button, top of the results
    RouteMap.jsx                  map, legend, forecast state
    RouteLayers.jsx               route lines and checkpoint popups (memoised)
    RiskFieldLayer.jsx            canvas risk field (inverse-distance interpolation)
    ForecastSlider.jsx            0–48 h slider, layer toggles, playback
    TruckMarkers.jsx              each truck's position at the slider hour, current-checkpoint ring
    RouteSummary.jsx, CheckpointTable.jsx
```

### Heatmap performance

The risk field is a custom Leaflet canvas layer. The interpolation weights between screen cells and forecast points depend only on the map view, so they are computed on pan or zoom. Moving the slider only re-blends 49 precomputed frames on a small offscreen image. Route lines and markers are memoised, so they don't re-render while scrubbing. In headless Chrome, each slider step renders within a frame (about 30 ms measured across two animation frames).

---

## Running locally

Requires Python 3.12+ and Node 18+.

```bash
# Backend
cd backend
pip install -r requirements.txt
cp .env.example .env          # sets DJANGO_DEBUG=True; add your ORS_API_KEY (free at openrouteservice.org)
python manage.py migrate
python manage.py runserver 8000

# Frontend (second terminal)
cd frontend
npm install
npm run dev                   # http://localhost:3000, /api is proxied to Django
```

On Windows, `start.ps1` or `start.bat` launches both (they set `DJANGO_DEBUG=True`).

### Tests

```bash
cd backend
python manage.py test routing                     # 48 tests, no network needed
python manage.py smoke_test                       # one live request (uses API quota)
python manage.py smoke_test --origin "Dallas, TX" --destination "Houston, TX" --weight 45000 --simulate
```

---

## Deployment

**Backend on Render.** `render.yaml` is a ready Blueprint (*New → Blueprint*, pick this repo). In the Render dashboard, set:

- `ORS_API_KEY`: your OpenRouteService key
- `CORS_ALLOWED_ORIGINS`: the frontend URL, e.g. `https://spotter.netlify.app`

`SECRET_KEY` is generated automatically, `DEBUG` is off, and the service hostname is added to `ALLOWED_HOSTS`. The health check is `/api/health/`. On the free tier the service sleeps when idle, so the first request after a pause takes about 30 s longer.

**Frontend on Netlify or Vercel.** Set the base directory to `frontend` (build `npm run build`, output `dist`; `netlify.toml` and `vercel.json` are included). Set `VITE_API_BASE_URL=https://<your-service>.onrender.com`.

### API limits

| Service | Free limit | Use per search |
|---|---|---|
| OpenRouteService directions | 2,000/day, 40/min | 3–7 calls (≈ 300–650 searches/day) |
| Nominatim | 1 request/s | 2, cached 24 h |
| Open-Meteo | 10,000 calls/day, 600/min | ~100–250 locations per search. If each location counts as one call, that's ≈ 40 uncached searches/day; repeats within 30 min are cached. Lower `MAX_GRID_POINTS` in `corridor_service.py` if needed. |

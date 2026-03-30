# INOVUES Online Savings Calculator — STATE.md
Last updated: 2026-03-29

## What this is
A client-facing web app that estimates HVAC energy savings from installing SWR (Secondary Window Retrofit) inserts on commercial buildings. Users enter an address + building details, and get back heating/cooling savings percentages based on EnergyPlus simulation data.

---

## Stack
| Layer | Tech | Location |
|---|---|---|
| Backend API | FastAPI (Python) | Railway — `web-production-86899.up.railway.app` |
| Database | PostgreSQL (`energy_model`) | Hetzner VPS `5.78.41.188` |
| Frontend | Vanilla HTML/CSS/JS (served by FastAPI) | Same Railway deployment |
| Repo | GitHub | `StephanBK/online_savings_calc` |

---

## Database
- **Host:** Hetzner VPS `5.78.41.188`
- **DB:** `energy_model`
- **Tables:** `jobs` (inputs) + `results` (outputs)
- **Rows:** 184,860 simulation jobs, fully populated
- **Key columns:**
  - `jobs`: `building_type`, `size`, `wwr`, `scenario`, `climate_zone` (US state abbrev), `floor_area_sqft`
  - `results`: `savings_heating_pct`, `savings_cooling_pct`, `savings_total_pct`, `baseline_heating_kbtu`, `baseline_cooling_kbtu`, `savings_heating_kbtu`, `savings_cooling_kbtu`
- **Connection:** Railway env var `DATABASE_URL` points to Hetzner Postgres (external port open)

---

## API Routes
| Route | Method | Description |
|---|---|---|
| `/` | GET | Serves `index.html` (client-facing frontend) |
| `/health` | GET | Returns `{"status": "ok"}` |
| `/calculate` | GET | Main endpoint — see params below |

### `/calculate` Query Params
| Param | Type | Default | Options |
|---|---|---|---|
| `address` | str | required | Any full US address |
| `building_type` | str | `office` | `office`, `hospitality`, `education`, `multifamily`, `hospital` |
| `size` | str | `medium` | `small`, `medium`, `large` |
| `pane_type` | str | `single` | `single`, `double` |
| `wwr` | float | `0.40` | `0.30`, `0.40`, `0.50`, `0.60`, `0.70`, `0.80` |

### Geocoding
- Uses **US Census Geocoder** (free, no API key) to resolve address → US state abbreviation → `climate_zone`

---

## Files in Repo
```
main.py          — FastAPI app (API + serves frontend)
index.html       — Client-facing frontend
requirements.txt — fastapi, uvicorn, psycopg2-binary, httpx
Procfile         — uvicorn start command for Railway
railway.json     — Railway build/deploy config
.gitignore
STATE.md         — This file
```

---

## Current Status (2026-03-29)
- ✅ Backend working and deployed on Railway
- ✅ DB query working (confirmed with 350 5th Ave test)
- ✅ Frontend deployed and "kinda working"
- 🔧 Frontend needs refinement (visual polish, UX improvements)

---

## Known Issues / Next Steps

### Frontend refinement (priority)
- Review and polish UI — layout, typography, spacing
- Consider adding a "what is WWR?" tooltip/explainer for non-technical users
- Mobile responsiveness check
- Loading state UX

### Future features (not started)
- **Dollar savings:** Requires user to input utility rate ($/kBtu or $/therm for heating, $/kWh for cooling) — backend already returns `baseline_kbtu` and `savings_kbtu` so math is trivial once input is added
- **Building area input:** Allow user to enter sq ft for scaled absolute savings (currently uses simulation's floor area)
- **LL97 penalty context:** For NYC buildings, show estimated LL97 fine reduction alongside energy savings
- **Lead capture:** CTA form or Calendly embed instead of just link to inovues.com/contact

---

## Deployment Notes
- Railway auto-deploys on push to `main`
- Env var `DATABASE_URL` must be set in Railway — format: `postgresql://user:pass@5.78.41.188:5432/energy_model`
- Health check path: `/health`

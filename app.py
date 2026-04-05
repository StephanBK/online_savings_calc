from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
import psycopg2
import psycopg2.extras
import os
import httpx
from typing import Optional
from pathlib import Path

app = FastAPI(title="INOVUES SWR Calculator")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

class IframeMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        response.headers.pop("x-frame-options", None)
        response.headers["Content-Security-Policy"] = "frame-ancestors *"
        return response

app.add_middleware(IframeMiddleware)

DATABASE_URL = os.environ["DATABASE_URL"]

def get_db():
    return psycopg2.connect(DATABASE_URL)

async def geocode_address(address: str) -> dict:
    try:
        url = "https://geocoding.geo.census.gov/geocoder/locations/onelineaddress"
        params = {"address": address, "benchmark": "Public_AR_Current", "format": "json"}
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(url, params=params)
            data = resp.json()
            matches = data.get("result", {}).get("addressMatches", [])
            if not matches:
                return None
            match = matches[0]
            state = match["addressComponents"]["state"]
            return {"state": state, "matched_address": match["matchedAddress"]}
    except Exception:
        return None

STATE_TO_ZONE = {
    "AL":"3A","AK":"8A","AZ":"2B","AR":"3A","CA":"3B-CA",
    "CO":"5B","CT":"5A","DE":"4A","FL":"1A","GA":"3A",
    "HI":"1A","ID":"5B","IL":"5A","IN":"5A","IA":"5A",
    "KS":"4A","KY":"4A","LA":"2A","ME":"6A","MD":"4A",
    "MA":"5A","MI":"5A","MN":"6A","MS":"2A","MO":"4A",
    "MT":"6B","NE":"5A","NV":"3B","NH":"6A","NJ":"4A",
    "NM":"4B","NY":"5A","NC":"3A","ND":"6A","OH":"5A",
    "OK":"3A","OR":"4C","PA":"5A","RI":"5A","SC":"3A",
    "SD":"6A","TN":"3A","TX":"2A","UT":"5B","VT":"6A",
    "VA":"4A","WA":"4C","WV":"4A","WI":"6A","WY":"6B","DC":"4A",
}

PRE1980_SUBTYPE_MAP = {
    "office": "medium_office",
    "multifamily": "midrise_apartment",
    "hospitality": "small_hotel",
}

@app.get("/health")
def health():
    return {"status": "ok", "version": "v3"}

@app.get("/calculate")
async def calculate(
    address:       str           = Query(...),
    building_type: str           = Query(...),
    size:          str           = Query("medium"),
    wwr:           float         = Query(0.40),
    pane_type:     str           = Query("single"),
    year_built:    Optional[int] = Query(None),
):
    geo = await geocode_address(address)
    if not geo:
        raise HTTPException(status_code=400, detail="Could not geocode address.")
    state    = geo["state"]
    scenario = "single_to_lowe" if pane_type == "single" else "double_to_triple"
    if year_built is not None and year_built < 1980:
        zone = STATE_TO_ZONE.get(state)
        if not zone:
            raise HTTPException(status_code=400, detail=f"Unknown state: {state}")
        subtype = PRE1980_SUBTYPE_MAP.get(building_type, "medium_office")
        try:
            conn = get_db()
            cur  = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            cur.execute("""
                SELECT heating_savings_pct, elec_savings_pct, cooling_savings_pct,
                       total_energy_savings_pct, baseline_heating_gas_gj,
                       baseline_total_elec_gj, retrofit_heating_gas_gj, retrofit_total_elec_gj
                FROM doe_pre1980_results
                WHERE zone = %s AND building_subtype = %s AND scenario = %s
                LIMIT 1
            """, (zone, subtype, "single_to_lowe"))
            row = cur.fetchone()
            conn.close()
            if not row:
                raise HTTPException(status_code=404, detail=f"No pre-1980 data for zone={zone}")
            GJ = 947.817
            return {
                "matched_address": geo["matched_address"],
                "state": state, "climate_zone": zone,
                "building_type": building_type, "era": "pre_1980",
                "savings_heating_pct": max(0.0, float(row["heating_savings_pct"])),
                "savings_cooling_pct": max(0.0, float(row["elec_savings_pct"])),
                "savings_total_pct":   max(0.0, float(row["total_energy_savings_pct"])),
            }
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"DB error: {str(e)}")

    wwr_rounded = round(round(wwr / 0.10) * 0.10, 2)
    wwr_rounded = max(0.30, min(0.80, wwr_rounded))
    try:
        conn = get_db()
        cur  = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("""
            SELECT r.savings_heating_pct, r.savings_cooling_pct, r.savings_total_pct,
                   r.baseline_heating_kbtu, r.baseline_cooling_kbtu,
                   r.savings_heating_kbtu, r.savings_cooling_kbtu
            FROM results r JOIN jobs j ON r.job_id = j.job_id
            WHERE j.climate_zone = %s AND j.building_type = %s
              AND j.wwr = %s AND j.scenario = %s AND j.size = %s
            LIMIT 1
        """, (state, building_type, wwr_rounded, scenario, size))
        row = cur.fetchone()
        conn.close()
        if not row:
            raise HTTPException(status_code=404, detail="No data found.")
        return {
            "matched_address": geo["matched_address"],
            "state": state, "building_type": building_type,
            "wwr": float(wwr_rounded), "era": "post_1980",
            "savings_heating_pct": float(row["savings_heating_pct"]),
            "savings_cooling_pct": float(row["savings_cooling_pct"]),
            "savings_total_pct":   float(row["savings_total_pct"]),
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"DB error: {str(e)}")

@app.get("/", response_class=HTMLResponse)
def root():
    import os
    # Log what we can see for debugging
    cwd = os.getcwd()
    app_files = os.listdir(cwd)
    static_path = os.path.join(cwd, "static", "index.html")
    if os.path.exists(static_path):
        with open(static_path, "r", encoding="utf-8") as f:
            return HTMLResponse(content=f.read())
    # Fallback: try relative to this file
    here = os.path.dirname(os.path.abspath(__file__))
    alt_path = os.path.join(here, "static", "index.html")
    if os.path.exists(alt_path):
        with open(alt_path, "r", encoding="utf-8") as f:
            return HTMLResponse(content=f.read())
    return HTMLResponse(
        content=f"<pre>cwd={cwd}\nfiles={app_files}\nstatic_path={static_path}\nhere={here}</pre>",
        status_code=200
    )

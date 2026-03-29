from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
import psycopg2
import psycopg2.extras
import os
import httpx
from typing import Optional

app = FastAPI(title="INOVUES SWR Calculator")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

DATABASE_URL = os.environ["DATABASE_URL"]

def get_db():
    return psycopg2.connect(DATABASE_URL)

async def geocode_address(address: str) -> dict:
    """Use US Census geocoder to get state from address."""
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
        state = match.get("addressComponents", {}).get("state", "")
        return {
            "matched_address": match.get("matchedAddress", address),
            "state": state.upper()
        }
    except Exception:
        return None

@app.get("/calculate")
async def calculate(
    address: str = Query(..., description="US building address"),
    building_type: str = Query("office", description="office, hospitality, education, multifamily, hospital"),
    wwr: float = Query(0.40, description="Window-to-wall ratio: 0.30, 0.40, 0.50, 0.60, 0.70, 0.80"),
    pane_type: str = Query("single", description="single or double — current window type"),
    size: str = Query("medium", description="small, medium, large")
):
    # Geocode address → state
    geo = await geocode_address(address)
    if not geo or not geo["state"]:
        raise HTTPException(status_code=400, detail="Could not geocode address. Please use a full US address e.g. '350 5th Ave, New York, NY 10118'")

    state = geo["state"]
    scenario = "single_to_lowe" if pane_type == "single" else "double_to_triple"

    # Round WWR to nearest 0.10
    wwr_rounded = round(round(wwr / 0.10) * 0.10, 2)
    if wwr_rounded < 0.30: wwr_rounded = 0.30
    if wwr_rounded > 0.80: wwr_rounded = 0.80

    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        # Query for exact match
        cur.execute("""
            SELECT
                r.savings_heating_pct,
                r.savings_cooling_pct,
                r.savings_total_pct,
                r.baseline_heating_kbtu,
                r.baseline_cooling_kbtu,
                r.savings_heating_kbtu,
                r.savings_cooling_kbtu,
                j.building_type,
                j.size,
                j.wwr,
                j.scenario,
                j.climate_zone,
                j.floor_area_sqft
            FROM results r
            JOIN jobs j ON r.job_id = j.job_id
            WHERE j.climate_zone = %s
              AND j.building_type = %s
              AND j.wwr = %s
              AND j.scenario = %s
              AND j.size = %s
            LIMIT 1
        """, (state, building_type, wwr_rounded, scenario, size))

        row = cur.fetchone()
        conn.close()

        if not row:
            raise HTTPException(
                status_code=404,
                detail=f"No data found for state={state}, building_type={building_type}, wwr={wwr_rounded}, scenario={scenario}. Try a different building type or size."
            )

        return {
            "matched_address": geo["matched_address"],
            "state": state,
            "building_type": building_type,
            "size": size,
            "wwr": float(wwr_rounded),
            "pane_type": pane_type,
            "scenario": scenario,
            "savings_heating_pct": float(row["savings_heating_pct"]),
            "savings_cooling_pct": float(row["savings_cooling_pct"]),
            "savings_total_pct": float(row["savings_total_pct"]),
            "baseline_heating_kbtu": float(row["baseline_heating_kbtu"]),
            "baseline_cooling_kbtu": float(row["baseline_cooling_kbtu"]),
            "savings_heating_kbtu": float(row["savings_heating_kbtu"]),
            "savings_cooling_kbtu": float(row["savings_cooling_kbtu"]),
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")

@app.get("/health")
def health():
    return {"status": "ok"}

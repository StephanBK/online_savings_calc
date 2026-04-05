from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
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

# Allow iframe embedding from Odoo
from fastapi import Request
from fastapi.responses import Response
from starlette.middleware.base import BaseHTTPMiddleware

class IframeMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        # Remove X-Frame-Options so Odoo can embed via iframe
        response.headers.pop("x-frame-options", None)
        # Allow embedding from any origin (scope to odoo domain if needed)
        response.headers["Content-Security-Policy"] = "frame-ancestors *"
        return response

app.add_middleware(IframeMiddleware)

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
            state = match["addressComponents"]["state"]
            return {
                "state": state,
                "matched_address": match["matchedAddress"],
            }
    except Exception:
        return None


# Climate zone mapping: US state -> ASHRAE zone
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
    "VA":"4A","WA":"4C","WV":"4A","WI":"6A","WY":"6B",
    "DC":"4A",
}

PRE1980_SUBTYPE_MAP = {
    "office":      "medium_office",
    "multifamily": "midrise_apartment",
    "hospitality": "small_hotel",
}


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
        raise HTTPException(status_code=400, detail="Could not geocode address. Please use a full US address e.g. '350 5th Ave, New York, NY 10118'")

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
                raise HTTPException(status_code=404, detail=f"No pre-1980 data for zone={zone}, subtype={subtype}")
            GJ = 947.817
            heat_pct = max(0.0, float(row["heating_savings_pct"]))
            elec_pct = max(0.0, float(row["elec_savings_pct"]))
            return {
                "matched_address": geo["matched_address"],
                "state": state, "climate_zone": zone,
                "building_type": building_type, "building_subtype": subtype,
                "year_built": year_built, "era": "pre_1980",
                "pane_type": pane_type, "scenario": "single_to_lowe",
                "savings_heating_pct": heat_pct,
                "savings_cooling_pct": elec_pct,
                "savings_total_pct": max(0.0, float(row["total_energy_savings_pct"])),
                "heating_savings_pct": heat_pct,
                "elec_savings_pct": elec_pct,
                "cooling_savings_pct": max(0.0, float(row["cooling_savings_pct"])),
                "total_energy_savings_pct": max(0.0, float(row["total_energy_savings_pct"])),
                "baseline_heating_kbtu": round(float(row["baseline_heating_gas_gj"]) * GJ, 0),
                "baseline_cooling_kbtu": round(float(row["baseline_total_elec_gj"]) * GJ, 0),
                "savings_heating_kbtu": round((float(row["baseline_heating_gas_gj"]) - float(row["retrofit_heating_gas_gj"])) * GJ, 0),
                "savings_cooling_kbtu": round((float(row["baseline_total_elec_gj"]) - float(row["retrofit_total_elec_gj"])) * GJ, 0),
            }
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")

    wwr_rounded = round(round(wwr / 0.10) * 0.10, 2)
    if wwr_rounded < 0.30: wwr_rounded = 0.30
    if wwr_rounded > 0.80: wwr_rounded = 0.80

    try:
        conn = get_db()
        cur  = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("""
            SELECT r.savings_heating_pct, r.savings_cooling_pct, r.savings_total_pct,
                   r.baseline_heating_kbtu, r.baseline_cooling_kbtu,
                   r.savings_heating_kbtu, r.savings_cooling_kbtu,
                   j.building_type, j.size, j.wwr, j.scenario, j.climate_zone, j.floor_area_sqft
            FROM results r JOIN jobs j ON r.job_id = j.job_id
            WHERE j.climate_zone = %s AND j.building_type = %s
              AND j.wwr = %s AND j.scenario = %s AND j.size = %s
            LIMIT 1
        """, (state, building_type, wwr_rounded, scenario, size))
        row = cur.fetchone()
        conn.close()
        if not row:
            raise HTTPException(status_code=404, detail=f"No data found for state={state}, building_type={building_type}, wwr={wwr_rounded}, scenario={scenario}. Try a different building type or size.")
        return {
            "matched_address": geo["matched_address"],
            "state": state, "building_type": building_type,
            "size": size, "wwr": float(wwr_rounded),
            "pane_type": pane_type, "scenario": scenario, "era": "post_1980",
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

@app.get("/debug")
def debug():
    import os
    base = os.path.dirname(os.path.abspath(__file__))
    result = {
        "abspath": base,
        "cwd": os.getcwd(),
        "files_in_base": os.listdir(base),
    }
    static = os.path.join(base, "static")
    if os.path.exists(static):
        result["files_in_static"] = os.listdir(static)
    else:
        result["static_exists"] = False
    return result

@app.get("/", response_class=HTMLResponse)
def root():
    import os
    # Use directory of this file — reliable on Railway
    base = os.path.dirname(os.path.abspath(__file__))
    html_path = os.path.join(base, "static", "index.html")
    with open(html_path, "r", encoding="utf-8") as f:
        return HTMLResponse(content=f.read())

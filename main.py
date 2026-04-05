import os
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from typing import Optional
import httpx
import psycopg2
import psycopg2.extras

app = FastAPI()

app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

DATABASE_URL = os.environ.get("DATABASE_URL", "")

@app.get("/health")
def health():
    return {"status": "ok", "version": "v4"}

@app.get("/", response_class=HTMLResponse)
def root():
    cwd = os.getcwd()
    files = os.listdir(cwd)
    static = os.path.join(cwd, "static", "index.html")
    if os.path.exists(static):
        return HTMLResponse(open(static, encoding="utf-8").read())
    return HTMLResponse(f"<pre>cwd={cwd}\nfiles={files}</pre>")

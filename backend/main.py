# backend/main.py
import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import logging

from backend import models   # ensure model classes are imported so metadata is populated
from backend.database import create_tables_async  # async helper
from backend.routes import router as api_router   # your API routes

logger = logging.getLogger("uvicorn.error")

app = FastAPI(title="EnVital GeoAware API")

# CORS (dev: allow all; restrict in prod)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Expose routes at the root (so /points and /city_heatmap work)
app.include_router(api_router, prefix="")

# Startup event to create tables using async engine
@app.on_event("startup")
async def startup_event():
    try:
        await create_tables_async()
        logger.info("Database tables ensured (async).")
    except Exception as e:
        logger.exception("Failed to create/ensure DB tables on startup: %s", e)

# Health & root helpers
@app.get("/health")
async def health():
    return {"status": "ok"}

@app.get("/")
async def root():
    return {"message": "EnVital GeoAware API. See /docs for Swagger UI."}

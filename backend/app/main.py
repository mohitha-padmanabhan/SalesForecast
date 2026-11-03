from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.routers import filters, forecast, auth
import os

app = FastAPI(title="Sales Forecast Engine")

origins = [
    "http://localhost:3000",
    "http://localhost:5173",
    "http://localhost:8080",
]

frontend_url = os.getenv("FRONTEND_URL")

if frontend_url:
    origins.append(frontend_url.rstrip("/"))

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(filters.router, prefix="/api/v1")
app.include_router(forecast.router, prefix="/api/v1")
app.include_router(auth.router)
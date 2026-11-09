from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.routers import filters, forecast
from app.routers import auth

app = FastAPI(title="Sales Forecast Engine")
app.include_router(filters.router, prefix="/api/v1")

# Configure CORS origins
from app.config import settings

origins = [
    settings.FRONTEND_URL,
    "http://localhost:3000",  # React / Next.js default
    "http://localhost:5173",  # Vite default
    "http://localhost:8080",  # Vue CLI default
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,  # Use ["*"] in development to allow all
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register endpoints

app.include_router(forecast.router)
app.include_router(auth.router)
from app.routers import state_locks
app.include_router(state_locks.router)

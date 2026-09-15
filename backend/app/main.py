'''
FastAPI application entrypoint for the Duality NVFlare backend.
Sets up CORS, health check, and API routes.
'''
from fastapi import FastAPI
from fastapi.responses import PlainTextResponse
from app.api.AppRoutes import router as api_router
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(title="Duality NVFlare Backend")

ALLOWED_ORIGINS = [
    "http://localhost:3000",
    "http://127.0.0.1:3000",
    "http://api.example.org",
    "https://app.example.org",
    "https://dev-app.example.org",
    "https://api.example.org"
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
    allow_credentials=False,
    max_age=86400,
)

@app.get("/health", response_class=PlainTextResponse)
def health_check():
    return "ok"

# Attach additional API routes
app.include_router(api_router)

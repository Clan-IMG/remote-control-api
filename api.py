import asyncio
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
import os

from src.app.config import CORS_ORIGINS, UPLOAD_DIR
from src.app.database import init_db
from src.app.redis_client import redis_client

# Logging konfigurieren
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


# Router imports
from src.app.routes.health import router as health_router
from src.app.routes.auth import router as auth_router
from src.app.routes.generations import router as generations_router
from src.app.routes.gallery import router as gallery_router
from src.app.routes.admin import router as admin_router
from src.app.routes.stats import router as stats_router


# ========== Lifespan ==========

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    logger.info("Starting PixelKid API...")
    await init_db()
    logger.info("Database initialized")
    
    # Ensure upload directory exists
    os.makedirs(UPLOAD_DIR, exist_ok=True)
    
    yield
    
    # Shutdown
    logger.info("Shutting down PixelKid API...")
    await redis_client.close()


# ========== App ==========

app = FastAPI(
    title="PixelKid API",
    description="Minecraft Pixel Art AI Generator API",
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc"
)


# ========== CORS ==========

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["*"],
    expose_headers=["*"],
    max_age=600,  # Cache preflight requests for 10 minutes
)


# Ensure CORS header is present on *all* responses (including errors from upstream)
@app.middleware("http")
async def ensure_cors_header(request, call_next):
    response = await call_next(request)
    try:
        # If configured origins include a wildcard, set wildcard; otherwise reflect allowed origins
        if isinstance(CORS_ORIGINS, list) and ("*" in CORS_ORIGINS or CORS_ORIGINS == ["*"]):
            response.headers.setdefault("Access-Control-Allow-Origin", "*")
        else:
            # Prefer the request Origin if it's in our allowed list
            origin = request.headers.get("origin")
            if origin and origin in CORS_ORIGINS:
                response.headers.setdefault("Access-Control-Allow-Origin", origin)
            else:
                # Fallback to first configured origin
                if isinstance(CORS_ORIGINS, list) and len(CORS_ORIGINS) > 0:
                    response.headers.setdefault("Access-Control-Allow-Origin", CORS_ORIGINS[0])
    except Exception:
        # Never fail the request because of header setting
        pass
    return response


# ========== Static Files ==========

# Serve uploaded images
if os.path.exists(UPLOAD_DIR):
    app.mount("/uploads", StaticFiles(directory=UPLOAD_DIR), name="uploads")


# ========== Router registrieren ==========

# Health & Root
app.include_router(health_router)

# Auth (register, login, API keys)
app.include_router(auth_router)

# Generations (create, list, status)
app.include_router(generations_router)

# Public Gallery
app.include_router(gallery_router)

# Admin Routes
app.include_router(admin_router)


# Stats
app.include_router(stats_router)


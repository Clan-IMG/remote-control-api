import os
from dotenv import load_dotenv

load_dotenv()

# ========== Database ==========
DATABASE_URL = os.getenv("DATABASE_URL", "mysql+aiomysql://root:password@localhost:3306/pixelkid")

# ========== Redis ==========
REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
REDIS_PORT = int(os.getenv("REDIS_PORT", 6379))
REDIS_PASSWORD = os.getenv("REDIS_PASSWORD", None)
REDIS_DB = int(os.getenv("REDIS_DB", 0))

# ========== CORS ==========
CORS_ORIGINS = os.getenv("CORS_ORIGINS", "http://localhost:3000,https://pixelkid.app").split(",")

# ========== Container Scaling ==========
MIN_CONTAINERS = int(os.getenv("MIN_CONTAINERS", 2))
MAX_CONTAINERS = int(os.getenv("MAX_CONTAINERS", 3))
SCALING_THRESHOLD = int(os.getenv("SCALING_THRESHOLD", 75))  # Prozent
MAXIMUM_REQUESTS = int(os.getenv("MAXIMUM_REQUESTS", 200))  # Pro Container

# Scaler lookahead: how many seconds to project queue growth for proactive scaling
SCALING_LOOKAHEAD_SECONDS = int(os.getenv("SCALING_LOOKAHEAD_SECONDS", 60))
# When projected queue exceeds this fraction of total capacity, scale up
SCALING_PROJECTED_UTILIZATION = float(os.getenv("SCALING_PROJECTED_UTILIZATION", 0.8))

# ========== Concurrent Workers ==========
MAX_CONCURRENT_WORKERS = int(os.getenv("MAX_CONCURRENT_WORKERS", 2))

# How long (seconds) a job is considered "processing" before it's considered stale
PROCESSING_TIMEOUT = int(os.getenv("PROCESSING_TIMEOUT", 600))  # 10 minutes

# ========== AI Configuration ==========
# Multiple API keys can be provided separated by comma for redundancy
STABILITY_API_KEYS = [key.strip() for key in os.getenv("STABILITY_API_KEY", "").split(",") if key.strip()]
REPLICATE_API_KEY = os.getenv("REPLICATE_API_KEY", "")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")

# ========== Storage ==========
UPLOAD_DIR = os.getenv("UPLOAD_DIR", "./uploads")
S3_BUCKET = os.getenv("S3_BUCKET", "")
S3_ENDPOINT = os.getenv("S3_ENDPOINT", "")
S3_ACCESS_KEY = os.getenv("S3_ACCESS_KEY", "")
S3_SECRET_KEY = os.getenv("S3_SECRET_KEY", "")

# ========== JWT / Auth ==========
JWT_SECRET = os.getenv("JWT_SECRET", "your-super-secret-jwt-key-change-in-production")
API_KEY_PREFIX = os.getenv("API_KEY_PREFIX", "pk_")

# ========== Email (SMTP) ==========
SMTP_HOST = os.getenv("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", 587))
SMTP_USERNAME = os.getenv("SMTP_USERNAME", "")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")
SMTP_FROM_EMAIL = os.getenv("SMTP_FROM_EMAIL", "noreply@pixelkid.app")
SMTP_FROM_NAME = os.getenv("SMTP_FROM_NAME", "Pixelkid")
SMTP_USE_TLS = os.getenv("SMTP_USE_TLS", "true").lower() == "true"

# OTP TTL in seconds (default 10 minutes)
OTP_TTL_SECONDS = int(os.getenv("OTP_TTL_SECONDS", 600))

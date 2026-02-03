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

# ========== Concurrent Workers ==========
MAX_CONCURRENT_WORKERS = int(os.getenv("MAX_CONCURRENT_WORKERS", 2))

# ========== AI Configuration ==========
STABILITY_API_KEY = os.getenv("STABILITY_API_KEY", "")
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

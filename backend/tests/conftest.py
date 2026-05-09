import os

os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
os.environ.setdefault("JWT_SECRET", "test-secret-at-least-32-characters")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/15")

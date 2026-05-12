import os

os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
os.environ.setdefault("JWT_SECRET", "test-secret-at-least-32-characters")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/15")
os.environ.setdefault("ADMIN_SEED_PASSWORD", "Admin@123456")
os.environ.setdefault("USER_SEED_PASSWORD", "User@123456")

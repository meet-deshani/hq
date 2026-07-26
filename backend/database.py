import os
import logging
from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

# Setup simple logger
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("db_connection")

# When true, NEVER run on SQLite — fail fast instead of silently losing data in
# production. Covers BOTH failure modes: no database configured at all
# (DATABASE_URL / DB_* unset) AND a configured database that is unreachable.
DB_REQUIRE = os.getenv("DB_REQUIRE", "").strip().lower() in ("1", "true", "yes", "on")

# Get connection parameters
DATABASE_URL = os.getenv("DATABASE_URL")

if not DATABASE_URL:
    db_user = os.getenv("DB_USER")
    db_pass = os.getenv("DB_PASSWORD")
    db_host = os.getenv("DB_HOST")
    db_port = os.getenv("DB_PORT", "5432")
    db_name = os.getenv("DB_NAME")
    
    if db_user and db_pass and db_host and db_name:
        DATABASE_URL = f"postgresql://{db_user}:{db_pass}@{db_host}:{db_port}/{db_name}"

# Production guard: if a real database is REQUIRED but none is configured, refuse
# to start rather than silently create an ephemeral SQLite DB. Prod sets
# DB_REQUIRE=true, so a missing/empty .env (no DATABASE_URL) crashes loudly here
# instead of booting on throwaway SQLite that gets wiped on every deploy.
if not DATABASE_URL and DB_REQUIRE:
    raise RuntimeError(
        "DB_REQUIRE is set but no database is configured (DATABASE_URL / DB_* "
        "environment variables are unset). Refusing to fall back to SQLite."
    )

# Setup engine and fallback if connection fails
is_sqlite = False
engine = None

if DATABASE_URL:
    try:
        logger.info(f"Connecting to database: {DATABASE_URL.split('@')[-1]}")
        engine = create_engine(DATABASE_URL, pool_pre_ping=True)
        # Test connection
        conn = engine.connect()
        conn.close()
        logger.info("Successfully connected to PostgreSQL database.")
    except Exception as e:
        if DB_REQUIRE:
            logger.error(
                f"Failed to connect to PostgreSQL database: {e}. "
                "DB_REQUIRE is set — refusing to fall back to SQLite."
            )
            raise
        logger.warning(f"Failed to connect to PostgreSQL database: {e}. Falling back to SQLite.")
        engine = None

if engine is None:
    is_sqlite = True
    # Fallback to local SQLite file in the database directory
    BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    db_dir = os.path.join(BASE_DIR, "database")
    os.makedirs(db_dir, exist_ok=True)
    sqlite_url = f"sqlite:///{os.path.join(db_dir, 'hq.db')}"
    logger.info(f"Using SQLite database: {sqlite_url}")
    engine = create_engine(sqlite_url, connect_args={"check_same_thread": False})

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

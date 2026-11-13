"""Runtime configuration, all from environment variables (see .env.example)."""
import os


def _bool(name: str, default: bool) -> bool:
    v = os.getenv(name)
    if v is None or v == "":
        return default
    return v.strip().lower() in ("1", "true", "yes", "on")


# --- storage -----------------------------------------------------------------
# "couchbase" for the full stack, "memory" for a no-dependency local run.
STORE_DRIVER = os.getenv("STORE_DRIVER", "memory")
COUCHBASE_CONN = os.getenv("COUCHBASE_CONN", "couchbase://couchbase")
COUCHBASE_USERNAME = os.getenv("COUCHBASE_USERNAME", "Administrator")
COUCHBASE_PASSWORD = os.getenv("COUCHBASE_PASSWORD", "password123")
COUCHBASE_BUCKET = os.getenv("COUCHBASE_BUCKET", "fieldservice")
COUCHBASE_SCOPE = os.getenv("COUCHBASE_SCOPE", "field")

# --- Databricks dump ------------------------------------------------------------
DUMP_DIR = os.getenv("DUMP_DIR", os.path.join(os.path.dirname(__file__), "..", "..", "data", "databricks-dump"))
# How often the backend checks the dump folder for a newer dt= partition.
DUMP_POLL_SECONDS = int(os.getenv("DUMP_POLL_SECONDS", "600"))
# Memory driver only: keep sites due for a visit within this many days (persona areas always kept).
MEMORY_WINDOW_DAYS = int(os.getenv("MEMORY_WINDOW_DAYS", "14"))
# "Today" for the demo. Empty = the export_date of the loaded dump, so the
# story (days since the last work order, visits due today) stays the same whenever it's run.
DEMO_TODAY = os.getenv("DEMO_TODAY", "")

# --- Knowledge Base publishing -------------------------------------------------
KB_ENABLED = _bool("KB_ENABLED", True)
KB_WINDOW_DAYS = int(os.getenv("KB_WINDOW_DAYS", "7"))
KB_PROFILE_LIMIT = int(os.getenv("KB_PROFILE_LIMIT", "150"))
KB_ALLOWED_ROLES = [r.strip() for r in os.getenv("KB_ALLOWED_ROLES", "field_technician,admin").split(",") if r.strip()]

# --- Couchbase Agent Operations Manager ------------------------------------------
AOM_URL = os.getenv("AOM_URL", "").rstrip("/")
AOM_AGENT_API_KEY = os.getenv("AOM_AGENT_API_KEY", "")
AOM_ADMIN_USERNAME = os.getenv("AOM_ADMIN_USERNAME", "admin")
AOM_ADMIN_PASSWORD = os.getenv("AOM_ADMIN_PASSWORD", "")
AOM_VERIFY_TLS = _bool("AOM_VERIFY_TLS", False)
# Register with AOM on startup (MCP server, agent identity, approval tier, RAG
# app) instead of running scripts/register_with_aom.py - see aom_bootstrap.py.
# Needs AOM_URL and AOM_ADMIN_PASSWORD; used by the Helm chart.
AOM_AUTO_REGISTER = _bool("AOM_AUTO_REGISTER", False)
# The AOM dashboard as a browser reaches it - linked from the story page.
AOM_DASHBOARD_URL = os.getenv("AOM_DASHBOARD_URL", "")
AOM_TIMEOUT_SECONDS = float(os.getenv("AOM_TIMEOUT_SECONDS", "20"))
AOM_LLM_PROVIDER = os.getenv("AOM_LLM_PROVIDER", "") or None
AOM_LLM_MODEL = os.getenv("AOM_LLM_MODEL", "") or None
AOM_MCP_SERVER_ID = os.getenv("AOM_MCP_SERVER_ID", "telco-field-service")
# The URL AOM (in its own compose stack) uses to reach this backend's MCP server.
AOM_MCP_PUBLIC_URL = os.getenv("AOM_MCP_PUBLIC_URL", "http://host.docker.internal:8203/fs/mcp")
# The field assistant is registered in AOM as a RAG Application. AOM attributes
# cache activity to an app by namespace prefix `rag:<app_id>:`, so every
# namespace the assistant uses (its own context cache and LLM calls as well as
# the app's /query endpoint) carries that prefix and shows up on AOM's RAG
# Applications page.
RAG_APP_ID = os.getenv("RAG_APP_ID", "telco-field-assistant")
RAG_APP_ENABLED = os.getenv("RAG_APP_ENABLED", "true").lower() == "true"
LLM_NAMESPACE_SITE = os.getenv("LLM_NAMESPACE_SITE", f"rag:{RAG_APP_ID}:site")
LLM_NAMESPACE_RUNBOOK = os.getenv("LLM_NAMESPACE_RUNBOOK", f"rag:{RAG_APP_ID}:runbook")
CONTEXT_NAMESPACE = os.getenv("CONTEXT_NAMESPACE", f"rag:{RAG_APP_ID}:site-context")

# --- Context cache -----------------------------------------------------------------
CONTEXT_CACHE_TTL_SECONDS = int(os.getenv("CONTEXT_CACHE_TTL_SECONDS", str(6 * 3600)))

# --- Sync Gateway (for Couchbase Lite replication) -----------------------------------
SG_ADMIN_URL = os.getenv("SG_ADMIN_URL", "").rstrip("/")  # e.g. http://sync-gateway:4985
SG_ADMIN_USERNAME = os.getenv("SG_ADMIN_USERNAME", "Administrator")
SG_ADMIN_PASSWORD = os.getenv("SG_ADMIN_PASSWORD", "password123")
SG_DB = os.getenv("SG_DB", "fieldservice")
# What the phone dials. Defaults to blank: the app falls back to EXPO_PUBLIC_SG_URL.
SG_PUBLIC_URL = os.getenv("SG_PUBLIC_URL", "")
SG_SESSION_TTL_SECONDS = int(os.getenv("SG_SESSION_TTL_SECONDS", str(24 * 3600)))

# --- app --------------------------------------------------------------------------------
APP_SECRET = os.getenv("APP_SECRET", "fs-demo-dev-secret-change-me")
# The app renews its token on every launch (/api/auth/refresh), so this is idle time.
APP_TOKEN_TTL_SECONDS = int(os.getenv("APP_TOKEN_TTL_SECONDS", str(30 * 24 * 3600)))
REQUEST_POLL_SECONDS = float(os.getenv("REQUEST_POLL_SECONDS", "2"))
CORS_ORIGINS = [o.strip() for o in os.getenv("CORS_ORIGINS", "*").split(",") if o.strip()]

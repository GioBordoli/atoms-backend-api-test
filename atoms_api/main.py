from fastapi import FastAPI
from fastapi.responses import RedirectResponse

# Import existing FastAPI app from root app.py
from app import app as legacy_app

# Reuse the legacy app directly
app: FastAPI = legacy_app

# Inject servers metadata into OpenAPI
SERVERS = [
    {"url": "https://atoms-api-709988093109.us-central1.run.app", "description": "prod"},
    {"url": "http://localhost:8080", "description": "local"},
]

_original_openapi = app.openapi

def _custom_openapi():
    schema = _original_openapi()
    schema["servers"] = SERVERS
    return schema

app.openapi = _custom_openapi  # type: ignore

# Provide versioned alias via redirect to root paths
@app.get("/v1")
async def v1_root():
    return RedirectResponse(url="/")

@app.get("/v1/{path:path}")
async def v1_redirect(path: str):
    return RedirectResponse(url=f"/{path}") 
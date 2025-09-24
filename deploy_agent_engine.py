import os
from vertexai import agent_engines

# Required env
PROJECT = os.environ.get("GOOGLE_CLOUD_PROJECT")
LOCATION = os.environ.get("GOOGLE_CLOUD_LOCATION", "us-central1")
SERVICE_ACCOUNT = os.environ.get("AGENT_SERVICE_ACCOUNT")  # optional
AGENT_DISPLAY_NAME = os.environ.get("AGENT_DISPLAY_NAME", "Requirements Refiner (ADK)")
AGENT_DESCRIPTION = os.environ.get("AGENT_DESCRIPTION", "ADK agent that refines requirements and can save to Supabase.")

# Optional: use secrets for Supabase
SUPABASE_URL_SECRET = os.environ.get("SUPABASE_URL_SECRET", "SUPABASE_URL")
SUPABASE_SERVICE_KEY_SECRET = os.environ.get("SUPABASE_SERVICE_KEY_SECRET", "SUPABASE_SERVICE_KEY")

# Model defaults
MODEL_NAME = os.environ.get("MODEL_NAME", "gemini-2.5-pro")
TEMPERATURE = os.environ.get("TEMPERATURE", "0.2")
PROMPT_VERSION = os.environ.get("PROMPT_VERSION", "v1")

# Import local ADK agent
from adk_app.agent import agent as local_agent

if not PROJECT:
    raise SystemExit("GOOGLE_CLOUD_PROJECT not set")

# Requirements and extra packages
requirements = "requirements.txt"
extra_packages = [
    "adk_app",
    "prompts",
]

# Environment variables for the runtime (no secrets inline)
# Vertex Agent Engine will inject secrets for these keys if configured below.
env_vars = {
    "MODEL_NAME": MODEL_NAME,
    "TEMPERATURE": TEMPERATURE,
    "PROMPT_VERSION": PROMPT_VERSION,
    # Secrets (must be created in Secret Manager in the same project)
    "SUPABASE_URL": {"secret": SUPABASE_URL_SECRET, "version": "latest"},
    "SUPABASE_SERVICE_KEY": {"secret": SUPABASE_SERVICE_KEY_SECRET, "version": "latest"},
}

# Resource controls (conservative defaults)
config = {
    "requirements": requirements,
    "extra_packages": extra_packages,
    "display_name": AGENT_DISPLAY_NAME,
    "description": AGENT_DESCRIPTION,
    "env_vars": env_vars,
    "min_instances": 1,
    "max_instances": 10,
    "resource_limits": {"cpu": "2", "memory": "4Gi"},
    "container_concurrency": 5,
}

if SERVICE_ACCOUNT:
    config["service_account"] = SERVICE_ACCOUNT

# Initialize client via env GOOGLE_CLOUD_PROJECT/LOCATION
print(f"Deploying agent to project={PROJECT} location={LOCATION}...")
remote_agent = agent_engines.create(
    agent=local_agent,
    config=config,
)

print("Deployed agent resource:")
print(remote_agent.resource_name) 
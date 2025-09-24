import os
import json
import time
import logging
import requests
from pathlib import Path
from datetime import datetime
from typing import List, Optional

import vertexai
from vertexai.generative_models import GenerativeModel, GenerationConfig
from google.genai import types

# Guard ADK-specific imports so API can run without google-adk installed
try:
    from google.adk.agents import Agent  # type: ignore
    from vertexai.agent_engines import AdkApp  # type: ignore
    HAS_ADK = True
except Exception:
    Agent = None  # type: ignore
    AdkApp = None  # type: ignore
    HAS_ADK = False

from dotenv import load_dotenv

# Load .env locally (not committed); in production use Agent secrets
load_dotenv()

# Logging setup
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# Env and model config
MODEL = os.getenv("MODEL_NAME", os.getenv("ADK_MODEL", "gemini-2.5-pro"))
PROJECT = os.getenv("GOOGLE_CLOUD_PROJECT")
LOCATION = os.getenv("GOOGLE_CLOUD_LOCATION", "us-central1")
TEMPERATURE = float(os.getenv("TEMPERATURE", "0.2"))
PROMPT_VERSION = os.getenv("PROMPT_VERSION", "v1")

# Supabase config
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_SERVICE_KEY = os.getenv("SUPABASE_SERVICE_KEY")
SUPABASE_TABLE = os.getenv("SUPABASE_TABLE", "requirements")

# File fetch limits
MAX_FILES = 10
MAX_FILE_SIZE_BYTES = 25 * 1024 * 1024  # 25MB
PER_FILE_TIMEOUT_SEC = 10
TOTAL_FETCH_TIMEOUT_SEC = 60
MAX_COMBINED_CHARS = 200_000
ALLOWED_EXT = {".pdf", ".md"}

# Init Vertex
if PROJECT:
    vertexai.init(project=PROJECT, location=LOCATION)

# Safety
safety_settings = [
    types.SafetySetting(
        category=types.HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT,
        threshold=types.HarmBlockThreshold.OFF,
    ),
]


def _read_text(p: Path) -> str:
    with p.open("r", encoding="utf-8") as f:
        return f.read()

PROMPTS_DIR = Path(__file__).resolve().parents[1] / "prompts"


def _render(template_name: str, replacements: dict) -> str:
    template = _read_text(PROMPTS_DIR / template_name)
    out = template
    for k, v in replacements.items():
        out = out.replace(f"{{{k}}}", v if v is not None else "")
    return out


def _gen_json(model: GenerativeModel, prompt: str, temperature: float = TEMPERATURE) -> dict:
    cfg = GenerationConfig(temperature=temperature)
    resp = model.generate_content(prompt, generation_config=cfg)
    text = (resp.text or "").strip().replace("```json", "").replace("```", "")
    return json.loads(text)


def _ext_ok(url: str) -> bool:
    try:
        ext = Path(url.split("?")[0].split("#")[0]).suffix.lower()
        return ext in ALLOWED_EXT
    except Exception:
        return False


def _fetch_file(url: str, session: requests.Session) -> bytes:
    # HEAD for size
    h = session.head(url, timeout=PER_FILE_TIMEOUT_SEC, allow_redirects=True)
    size = int(h.headers.get("Content-Length", "0"))
    if size and size > MAX_FILE_SIZE_BYTES:
        raise ValueError(f"file too large: {size} bytes")
    # GET
    r = session.get(url, timeout=PER_FILE_TIMEOUT_SEC, allow_redirects=True)
    r.raise_for_status()
    content = r.content
    if len(content) > MAX_FILE_SIZE_BYTES:
        raise ValueError("file exceeds size limit after download")
    return content


def fetch_file_urls(file_urls: List[str]) -> dict:
    """Fetch and parse files from HTTPS URLs with validation and caps.

    Returns dict {"text": concatenated_text, "truncated": bool}
    """
    if not file_urls:
        return {"text": "", "truncated": False}
    if len(file_urls) > MAX_FILES:
        raise ValueError("Too many files (max 10)")

    start = time.time()
    combined = []
    with requests.Session() as s:
        for url in file_urls:
            if not (url.startswith("https://") or url.startswith("http://")):
                raise ValueError("Only HTTP(S) URLs allowed")
            if not _ext_ok(url):
                raise ValueError("Unsupported file type; only .pdf and .md allowed")
            if time.time() - start > TOTAL_FETCH_TIMEOUT_SEC:
                raise TimeoutError("Total fetch timeout exceeded")

            content = _fetch_file(url, s)
            path = Path(url.split("?")[0].split("#")[0])
            ext = path.suffix.lower()
            text = ""
            try:
                if ext == ".md":
                    text = content.decode("utf-8", errors="ignore")
                else:  # .pdf
                    try:
                        from pypdf import PdfReader
                        from io import BytesIO
                        reader = PdfReader(BytesIO(content))
                        pages = []
                        for p in reader.pages:
                            pages.append(p.extract_text() or "")
                        text = "\n".join(pages)
                    except Exception:
                        text = content.decode("latin-1", errors="ignore")
            except Exception as e:
                logger.warning("file_parse_failed", extra={"url": url, "error": str(e)})
                raise ValueError("Failed to parse file")

            combined.append(text)
            if sum(len(c) for c in combined) > MAX_COMBINED_CHARS:
                joined = "\n".join(combined)[:MAX_COMBINED_CHARS]
                logger.info("combined_truncated", extra={"cap": MAX_COMBINED_CHARS})
                return {"text": joined, "truncated": True}

    return {"text": "\n".join(combined), "truncated": False}


def refine_requirement(
    requirement: str,
    systemName: str = "",
    objective: str = "",
    file_urls: List[str] | None = None,
) -> dict:
    run_id = os.getenv("RUN_ID_OVERRIDE") or str(int(time.time() * 1000))
    logger.info("analysis_start", extra={"run_id": run_id})

    if not requirement or len(requirement.strip()) == 0:
        raise ValueError("requirement is required")

    fetched = {"text": "", "truncated": False}
    if file_urls:
        fetched = fetch_file_urls(file_urls)
        logger.info("files_fetched", extra={"run_id": run_id, "count": len(file_urls), "truncated": fetched["truncated"]})

    model = GenerativeModel(MODEL)

    p1 = _render(
        "step1.txt",
        {
            "system_name": systemName or "",
            "objective": objective or "",
            "original_requirement": requirement,
            "req_id": "",
            "analysis_timestamp": datetime.now().isoformat(),
        },
    )
    step1 = _gen_json(model, p1, TEMPERATURE)

    step2 = {
        "regulation_document": "",
        "relevant_passages": [],
        "compliance_concerns": [],
        "regulatory_keywords": [],
        "analysis_timestamp": datetime.now().isoformat(),
    }

    p3 = _render(
        "step3.txt",
        {
            "requirement_analysis_json": json.dumps(step1, indent=2),
            "regulation_analysis_json": json.dumps(step2, indent=2),
            "analysis_timestamp": datetime.now().isoformat(),
        },
    )
    step3 = _gen_json(model, p3, TEMPERATURE)

    outs = {
        "analysisJson": [
            json.dumps(
                {
                    "Original Requirement": step1.get("original_requirement", requirement),
                    "EARS Generated Requirement": step1.get("ears_format", ""),
                    "EARS Pattern": step1.get("requirement_pattern", ""),
                    "EARS_SYNTAX_TEMPLATE": "When <trigger>, the <system> shall <response>",
                    "INCOSE_FORMAT": step1.get("incose_format", ""),
                    "INCOSE_REQUIREMENT_FEEDBACK": step1.get("feedback", ""),
                }
            )
        ],
        "analysisJson2": [
            json.dumps(
                {
                    "RELEVANT_REGULATIONS": [],
                    "COMPLIANCE_FEEDBACK": "",
                }
            )
        ],
        "analysisJson3": [
            json.dumps(
                {
                    "ENHANCED_REQUIREMENT_EARS": step3.get("final_requirement_ears", ""),
                    "ENHANCED_REQUIREMENT_INCOSE": step3.get("final_requirement_incose", ""),
                    "ENHANCED_GENERAL_FEEDBACK": step3.get("enhancement_summary", ""),
                }
            )
        ],
    }

    properties = {
        "final_requirement_ears": step3.get("final_requirement_ears", ""),
        "final_requirement_incose": step3.get("final_requirement_incose", ""),
        "compliance_status": step3.get("compliance_status", ""),
        "final_quality_rating": step3.get("final_quality_rating", ""),
        "prompt_version": PROMPT_VERSION,
        "model_name": MODEL,
    }

    result = {
        "status": "success",
        "run_id": run_id,
        "analysisJson": step1,
        "analysisJson2": step2,
        "analysisJson3": step3,
        "outputs": outs,
        "properties": properties,
    }

    logger.info("analysis_finish", extra={"run_id": run_id})
    return result


def _generate_external_id() -> str:
    # Global unique req id (timestamp-based)
    return f"REQ-{int(time.time()*1000)}"


def save_requirement_supabase(
    document_id: str,
    block_id: str,
    name: str,
    final_requirement_incose: str,
    final_requirement_ears: str,
    compliance_status: Optional[str] = "",
    final_quality_rating: Optional[int | str] = None,
    regulatory_traceability: Optional[List[str]] = None,
    original_requirement: Optional[str] = None,
    description: Optional[str] = None,
    created_by: Optional[str] = None,
    tags: Optional[List[str]] = None,
) -> dict:
    """Insert requirement into Supabase requirements table via REST.

    Returns: { id, external_id }
    """
    if not SUPABASE_URL or not SUPABASE_SERVICE_KEY:
        raise RuntimeError("Supabase config missing")

    external_id = _generate_external_id()

    ai_analysis = {
        "final_requirement_ears": final_requirement_ears,
        "final_requirement_incose": final_requirement_incose,
        "compliance_status": compliance_status or "",
        "final_quality_rating": final_quality_rating,
        "regulatory_traceability": regulatory_traceability or [],
    }
    properties = {
        "final_requirement_ears": final_requirement_ears,
        "final_requirement_incose": final_requirement_incose,
        "compliance_status": compliance_status or "",
        "final_quality_rating": final_quality_rating,
        "prompt_version": PROMPT_VERSION,
        "model_name": MODEL,
    }

    payload = {
        "external_id": external_id,
        "document_id": document_id,
        "block_id": block_id,
        "name": name,
        "description": description,
        "tags": tags or [],
        "original_requirement": original_requirement,
        "enchanced_requirement": final_requirement_incose,
        "ai_analysis": ai_analysis,
        "properties": properties,
        # Defaults: status active, format incose set by DB
    }
    if created_by:
        payload["created_by"] = created_by

    url = f"{SUPABASE_URL}/rest/v1/{SUPABASE_TABLE}"
    headers = {
        "apikey": SUPABASE_SERVICE_KEY,
        "Authorization": f"Bearer {SUPABASE_SERVICE_KEY}",
        "Content-Type": "application/json",
        "Prefer": "return=representation",
    }

    r = requests.post(url, headers=headers, data=json.dumps(payload), timeout=15)
    if r.status_code >= 400:
        msg = r.text
        code = "INTERNAL_ERROR"
        status = r.status_code
        # Map FK issues to NOT_FOUND where possible
        if "foreign key" in msg.lower() or r.status_code == 409:
            code = "NOT_FOUND"
            status = 404
        elif r.status_code == 400:
            code = "VALIDATION_ERROR"
        logger.error("supabase_insert_failed", extra={"status": r.status_code, "body": msg})
        raise RuntimeError(json.dumps({"error": "Save failed", "code": code, "status": status}))

    data = r.json()
    if not isinstance(data, list) or not data:
        raise RuntimeError(json.dumps({"error": "Save returned no rows", "code": "INTERNAL_ERROR", "status": 500}))

    row = data[0]
    return {"id": row.get("id"), "external_id": external_id}


# Only create Agent/AdkApp when ADK is available (not required for API proxy)
if HAS_ADK:
    agent = Agent(
        model=MODEL,
        name="requirements_refiner",
        instruction=(
            "You refine software requirements using INCOSE/EARS and produce legacy-compatible outputs.\n"
            "Use fetch_file_urls to retrieve document content if provided.\n"
            "Use save_requirement_supabase to persist a finalized requirement."
        ),
        tools=[refine_requirement, fetch_file_urls, save_requirement_supabase],
    )
    app = AdkApp(agent=agent)
else:
    agent = None  # type: ignore
    app = None  # type: ignore 
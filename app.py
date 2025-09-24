import os
import json
import logging
from datetime import datetime
from fastapi import FastAPI, HTTPException, BackgroundTasks, File, UploadFile, Form, Query, Path as FPath
from fastapi.middleware.cors import CORSMiddleware
from typing import List, Dict, Any
import google.generativeai as genai
try:
    from google.cloud import storage  # type: ignore
    HAS_GCS = True
except Exception:
    storage = None  # type: ignore
    HAS_GCS = False
import PyPDF2
from io import BytesIO
import traceback
import uuid
from werkzeug.utils import secure_filename
import re
from pathlib import Path
from adk_app.agent import refine_requirement as agent_refine, save_requirement_supabase as agent_save
from pydantic import BaseModel, Field, ConfigDict

# Import Pydantic models
from models import AnalysisRequest, PipelineStartParams, AnalysisResult, RequirementCreateRequest, RequirementRecord, RequirementListResponse

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="ATOMS Requirements Analysis API",
    description="""
## Overview
Professional API for analyzing software requirements against INCOSE/EARS standards and regulatory compliance.

### Key Features
- **INCOSE/EARS Standards Compliance**: Automatically analyze and rewrite requirements following industry standards
- **Regulatory Compliance**: Check requirements against uploaded regulation documents
- **Organization-based Document Management**: Secure, isolated document storage per organization
- **AI-Powered Analysis**: Three-step analysis pipeline using Google's Gemini AI
- **Asynchronous Processing**: Support for both sync and async analysis workflows

### Authentication
This API uses Google Cloud Identity tokens for authentication. All users must be part of the authorized domain.

### Usage
1. Upload regulation documents to your organization
2. Submit requirements for analysis
3. Receive enhanced, compliant requirements with detailed feedback

Built with FastAPI and deployed on Google Cloud Run.
    """,
    version="2.0.0",
    contact={
        "name": "ATOMS Engineering Team",
        "email": "support@atoms.tech",
    },
    license_info={
        "name": "Proprietary",
        "url": "https://atoms.tech/license",
    },
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json"
)

# Enable CORS
ALLOWED_ORIGINS = os.getenv("ALLOWED_ORIGINS", "http://localhost:3000,https://atoms.tech")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[origin.strip() for origin in ALLOWED_ORIGINS.split(",") if origin.strip()],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize Google AI
if os.getenv('GEMINI_API_KEY'):
    genai.configure(api_key=os.getenv('GEMINI_API_KEY'))

# Initialize Google Cloud Storage client (optional)
storage_client = storage.Client() if HAS_GCS else None

# In-memory job storage (in production, use Redis or database)
job_storage: Dict[str, Dict[str, Any]] = {}

# In-memory fallback stores for requirements when GCS is unavailable
INMEM_LAST_ID: Dict[str, int] = {}
INMEM_INPUTS: Dict[str, Dict[str, Any]] = {}
INMEM_REQUIREMENTS: Dict[str, Dict[str, Any]] = {}

# --- Helper Functions ---

PROMPTS_DIR = Path(__file__).resolve().parent / "prompts"

def _read_prompt_template(filename: str) -> str:
    template_path = PROMPTS_DIR / filename
    with open(template_path, "r", encoding="utf-8") as f:
        return f.read()

def _format_prompt(template: str, replacements: Dict[str, str]) -> str:
    # Simple placeholder replacement without interfering with JSON braces
    rendered = template
    for key, value in replacements.items():
        rendered = rendered.replace(f"{{{key}}}", value)
    return rendered

def get_organization_bucket_name(organization_id: str) -> str:
    """Get bucket name for organization."""
    return f"{organization_id}-requirements"

def create_bucket_if_not_exists(bucket_name: str):
    """Create bucket if it doesn't exist (requires GCS)."""
    if not HAS_GCS:
        raise HTTPException(status_code=501, detail="GCS not configured")
    try:
        bucket = storage_client.bucket(bucket_name)  # type: ignore[arg-type]
        if not bucket.exists():
            bucket = storage_client.create_bucket(bucket_name, location="US")  # type: ignore
            logger.info(f"Created bucket: {bucket_name}")
        return bucket
    except Exception as e:
        logger.error(f"Error creating bucket {bucket_name}: {str(e)}")
        raise

def get_versioned_filename(bucket, base_filename: str) -> str:
    """Get a versioned filename if the base filename already exists."""
    if not HAS_GCS:
        return base_filename
    name, ext = os.path.splitext(base_filename)
    blob = bucket.blob(base_filename)
    if not blob.exists():
        return base_filename
    
    counter = 1
    while True:
        candidate = f"{name}_{counter}{ext}"
        if not bucket.blob(candidate).exists():
            return candidate
        counter += 1

def _next_req_id_inmem(org_id: str) -> str:
    last = INMEM_LAST_ID.get(org_id, 0) + 1
    INMEM_LAST_ID[org_id] = last
    return f"{last:04d}"

def next_req_id(organization_id: str) -> str:
    if HAS_GCS:
        bucket = create_bucket_if_not_exists(get_organization_bucket_name(organization_id))
        return _next_req_id(bucket)
    return _next_req_id_inmem(organization_id)

async def list_organization_documents(organization_id: str) -> List[Dict[str, Any]]:
    """List all documents in an organization's bucket."""
    try:
        bucket_name = get_organization_bucket_name(organization_id)
        if not HAS_GCS:
            raise HTTPException(status_code=501, detail="GCS not configured")
        bucket = storage_client.bucket(bucket_name)  # type: ignore
        
        if not bucket.exists():
            return []
        
        documents = []
        for blob in bucket.list_blobs():
            documents.append({
                "name": blob.name,
                "size": blob.size,
                "created": blob.time_created.isoformat() if blob.time_created else None,
                "updated": blob.updated.isoformat() if blob.updated else None
            })
        return documents
    except Exception as e:
        logger.error(f"Error listing documents for organization {organization_id}: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to list documents: {str(e)}")

async def delete_organization_document(organization_id: str, document_name: str) -> bool:
    """Delete a document from an organization's bucket."""
    try:
        bucket_name = get_organization_bucket_name(organization_id)
        if not HAS_GCS:
            raise HTTPException(status_code=501, detail="GCS not configured")
        bucket = storage_client.bucket(bucket_name)  # type: ignore
        
        if not bucket.exists():
            raise FileNotFoundError(f"Organization bucket not found: {bucket_name}")
        
        blob = bucket.blob(document_name)
        if not blob.exists():
            raise FileNotFoundError(f"Document not found: {document_name}")
        
        blob.delete()
        logger.info(f"Deleted document {document_name} from organization {organization_id}")
        return True
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"Error deleting document {document_name} for organization {organization_id}: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to delete document: {str(e)}")

def extract_text_from_pdf(pdf_content: bytes) -> str:
    """Extract text from PDF bytes."""
    try:
        pdf_reader = PyPDF2.PdfReader(BytesIO(pdf_content))
        text = ""
        for page in pdf_reader.pages:
            text += page.extract_text() + "\n"
        return text
    except Exception as e:
        logger.error(f"Error extracting PDF text: {str(e)}")
        return ""

async def get_regulation_document(document_name: str, organization_id: str) -> str:
    """Download and extract text from regulation document in organization's bucket."""
    if not HAS_GCS:
        raise FileNotFoundError("GCS not configured")
    try:
        bucket_name = get_organization_bucket_name(organization_id)
        bucket = storage_client.bucket(bucket_name)  # type: ignore
        
        if not bucket.exists():
            raise FileNotFoundError(f"Organization bucket not found: {bucket_name}")
        
        possible_extensions = ['.pdf', '.PDF']
        for ext in possible_extensions:
            try:
                blob_name = f"{document_name}{ext}" if not document_name.endswith(ext) else document_name
                blob = bucket.blob(blob_name)
                if blob.exists():
                    pdf_content = blob.download_as_bytes()
                    return extract_text_from_pdf(pdf_content)
            except Exception as e:
                logger.warning(f"Failed to download {blob_name}: {str(e)}")
                continue
        
        raise FileNotFoundError(f"Document {document_name} not found in bucket {bucket_name}")
    except Exception as e:
        logger.error(f"Error getting regulation document: {str(e)}")
        raise

async def upload_file_to_organization_bucket(file_content: bytes, filename: str, organization_id: str) -> str:
    """Upload file to organization's Cloud Storage bucket."""
    if not HAS_GCS:
        raise HTTPException(status_code=501, detail="GCS upload not available")
    try:
        bucket_name = get_organization_bucket_name(organization_id)
        bucket = create_bucket_if_not_exists(bucket_name)
        
        secure_name = secure_filename(filename)
        final_filename = get_versioned_filename(bucket, secure_name)
        
        blob = bucket.blob(final_filename)
        blob.upload_from_string(file_content, content_type='application/pdf')
        
        logger.info(f"File {final_filename} uploaded to organization {organization_id} bucket")
        return final_filename
    except Exception as e:
        logger.error(f"Error uploading file: {str(e)}")
        raise

async def analyze_requirement_step1(original_requirement: str, system_name: str = "", objective: str = "", req_id: str = "", temperature: float = 0.1) -> Dict:
    """Step 1: Initial Requirements Analysis using INCOSE and EARS standards."""
    template = _read_prompt_template("step1.txt")
    prompt = _format_prompt(template, {
        "system_name": system_name or "",
        "objective": objective or "",
        "original_requirement": original_requirement or "",
        "req_id": req_id or "",
        "analysis_timestamp": datetime.now().isoformat(),
    })
    try:
        model = genai.GenerativeModel('gemini-1.5-flash')
        response = await model.generate_content_async(
            prompt,
            generation_config=genai.types.GenerationConfig(temperature=temperature)
        )
        response_text = response.text.strip().replace("```json", "").replace("```", "")
        return json.loads(response_text)
    except Exception as e:
        logger.error(f"Error in Step 1 analysis: {str(e)}")
        raise

async def analyze_regulation_step2(requirement_analysis: Dict, regulation_text: str, regulation_doc_name: str, temperature: float = 0.1) -> Dict:
    """Step 2: Regulatory Research and Compliance Analysis."""
    template = _read_prompt_template("step2.txt")
    prompt = _format_prompt(template, {
        "requirement_analysis_json": json.dumps(requirement_analysis, indent=2),
        "regulation_doc_name": regulation_doc_name,
        "regulation_text": (regulation_text[:10000] + ("..." if len(regulation_text) > 10000 else "")),
        "analysis_timestamp": datetime.now().isoformat(),
    })
    try:
        model = genai.GenerativeModel('gemini-1.5-flash')
        response = await model.generate_content_async(
            prompt,
            generation_config=genai.types.GenerationConfig(temperature=temperature)
        )
        response_text = response.text.strip().replace("```json", "").replace("```", "")
        return json.loads(response_text)
    except Exception as e:
        logger.error(f"Error in Step 2 analysis: {str(e)}")
        raise

async def analyze_compliance_step3(requirement_analysis: Dict, regulation_analysis: Dict, temperature: float = 0.1) -> Dict:
    """Step 3: Compliance Integration and Enhanced Requirements."""
    template = _read_prompt_template("step3.txt")
    prompt = _format_prompt(template, {
        "requirement_analysis_json": json.dumps(requirement_analysis, indent=2),
        "regulation_analysis_json": json.dumps(regulation_analysis, indent=2),
        "analysis_timestamp": datetime.now().isoformat(),
    })
    try:
        model = genai.GenerativeModel('gemini-1.5-flash')
        response = await model.generate_content_async(
            prompt,
            generation_config=genai.types.GenerationConfig(temperature=temperature)
        )
        response_text = response.text.strip().replace("```json", "").replace("```", "")
        return json.loads(response_text)
    except Exception as e:
        logger.error(f"Error in Step 3 analysis: {str(e)}")
        raise

async def run_analysis_job(job_id: str, analysis_params: Dict):
    """Run the analysis job in background."""
    try:
        logger.info(f"Starting analysis job {job_id}")
        job_storage[job_id]['state'] = 'RUNNING'
        
        req = AnalysisRequest(**analysis_params)

        # Step 1
        analysis_json = await analyze_requirement_step1(
            req.original_requirement, req.system_name, req.objective, req.req_id, req.temperature
        )
        
        # Step 2
        try:
            regulation_text = await get_regulation_document(req.regulation_document_name, req.organizationId)
            analysis_json2 = await analyze_regulation_step2(
                analysis_json, regulation_text, req.regulation_document_name, req.temperature
            )
        except FileNotFoundError:
            analysis_json2 = {
                "regulation_document": req.regulation_document_name,
                "relevant_passages": [],
                "compliance_concerns": ["No regulation document found for analysis"],
                "regulatory_keywords": [],
                "analysis_timestamp": datetime.now().isoformat()
            }
        
        # Step 3
        analysis_json3 = await analyze_compliance_step3(
            analysis_json, analysis_json2, req.temperature
        )
        
        response_data = {
            "status": "success",
            "analysisJson": analysis_json,
            "analysisJson2": analysis_json2, 
            "analysisJson3": analysis_json3,
            "processed_timestamp": datetime.now().isoformat()
        }
        
        job_storage[job_id]['state'] = 'DONE'
        job_storage[job_id]['result'] = response_data
        job_storage[job_id]['completed_at'] = datetime.now().isoformat()
        logger.info(f"Analysis job {job_id} completed successfully")
        
    except Exception as e:
        logger.error(f"Job {job_id} failed: {str(e)}")
        job_storage[job_id]['state'] = 'FAILED'
        job_storage[job_id]['error'] = str(e)
        job_storage[job_id]['completed_at'] = datetime.now().isoformat()

# --- GCS requirements persistence helpers ---

def _requirements_prefix() -> str:
    return "requirements"

def _inputs_prefix() -> str:
    return "inputs"

def _index_blob(bucket) -> Any:
    return bucket.blob(f"{_requirements_prefix()}/index.json")

def _load_index(bucket) -> Dict[str, Any]:
    blob = _index_blob(bucket)
    if not blob.exists():
        return {"last_id": 0}
    content = blob.download_as_text()
    try:
        return json.loads(content)
    except Exception:
        return {"last_id": 0}

def _save_index_with_cas(bucket, new_index: Dict[str, Any], expected_generation: int) -> bool:
    blob = _index_blob(bucket)
    data = json.dumps(new_index).encode("utf-8")
    try:
        blob.upload_from_string(data, if_generation_match=expected_generation, content_type="application/json")
        return True
    except Exception as e:
        logger.warning(f"Index CAS write failed: {e}")
        return False

def _next_req_id(bucket) -> str:
    # CAS loop to increment last_id
    blob = _index_blob(bucket)
    while True:
        current_generation = 0
        if blob.exists():
            blob.reload()
            current_generation = blob.generation or 0
        index = _load_index(bucket)
        next_id = (index.get("last_id") or 0) + 1
        new_index = {"last_id": next_id}
        if _save_index_with_cas(bucket, new_index, expected_generation=current_generation):
            return f"{next_id:04d}"

async def _persist_input_json(organization_id: str, req_id: str, payload: Dict[str, Any]):
    if HAS_GCS:
        bucket = create_bucket_if_not_exists(get_organization_bucket_name(organization_id))
        blob = bucket.blob(f"{_inputs_prefix()}/{req_id}.json")
        blob.upload_from_string(json.dumps(payload), content_type="application/json")
        return
    # in-memory fallback
    INMEM_INPUTS[f"{organization_id}:{req_id}"] = payload

async def _persist_requirement_json(organization_id: str, req_id: str, record: Dict[str, Any]):
    if HAS_GCS:
        bucket = create_bucket_if_not_exists(get_organization_bucket_name(organization_id))
        blob = bucket.blob(f"{_requirements_prefix()}/{req_id}.json")
        blob.upload_from_string(json.dumps(record), content_type="application/json")
        return
    INMEM_REQUIREMENTS[f"{organization_id}:{req_id}"] = record

async def _get_requirement_json(organization_id: str, req_id: str) -> Dict[str, Any]:
    if HAS_GCS:
        bucket = storage_client.bucket(get_organization_bucket_name(organization_id))  # type: ignore
        blob = bucket.blob(f"{_requirements_prefix()}/{req_id}.json")
        if not blob.exists():
            raise FileNotFoundError("Requirement not found")
        return json.loads(blob.download_as_text())
    key = f"{organization_id}:{req_id}"
    if key not in INMEM_REQUIREMENTS:
        raise FileNotFoundError("Requirement not found")
    return INMEM_REQUIREMENTS[key]

async def _list_requirements(organization_id: str, page: int = 1, page_size: int = 20) -> Dict[str, Any]:
    if HAS_GCS:
        bucket = storage_client.bucket(get_organization_bucket_name(organization_id))  # type: ignore
        if not bucket.exists():
            return {"items": [], "total": 0, "page": page, "pageSize": page_size}
        prefix = f"{_requirements_prefix()}/"
        blobs = list(bucket.list_blobs(prefix=prefix))
        items = []
        for b in blobs:
            if not b.name.endswith(".json") or b.name.endswith("index.json"):
                continue
            try:
                items.append(json.loads(b.download_as_text()))
            except Exception:
                continue
    else:
        items = [v for k, v in INMEM_REQUIREMENTS.items() if k.startswith(f"{organization_id}:")]
    items.sort(key=lambda r: r.get("req_id", ""))
    total = len(items)
    start = max((page - 1) * page_size, 0)
    end = start + page_size
    return {"items": items[start:end], "total": total, "page": page, "pageSize": page_size}

# --- Mapping to legacy outputs ---

def _build_legacy_outputs(result: Dict[str, Any]) -> Dict[str, Any]:
    analysis = result.get("analysisJson", {})
    regulation = result.get("analysisJson2", {})
    final = result.get("analysisJson3", {})

    # analysisJson array element
    a = {
        "Original Requirement": analysis.get("original_requirement", ""),
        "EARS Generated Requirement": analysis.get("ears_format", ""),
        "EARS Pattern": analysis.get("requirement_pattern", ""),
        "EARS_SYNTAX_TEMPLATE": "When <trigger>, the <system> shall <response>",
        "INCOSE_FORMAT": analysis.get("incose_format", ""),
        "INCOSE_REQUIREMENT_FEEDBACK": analysis.get("feedback", ""),
    }

    # analysisJson2 array element
    relevant = []
    for p in regulation.get("relevant_passages", []) or []:
        section = p.get("section") or ""
        text = p.get("text") or ""
        if section or text:
            relevant.append(f"{section}: {text}".strip())
    compliance_feedback = "; ".join(regulation.get("compliance_concerns", []) or [])
    b = {
        "RELEVANT_REGULATIONS": relevant,
        "COMPLIANCE_FEEDBACK": compliance_feedback,
    }

    # analysisJson3 array element
    c = {
        "ENHANCED_REQUIREMENT_EARS": final.get("final_requirement_ears", ""),
        "ENHANCED_REQUIREMENT_INCOSE": final.get("final_requirement_incose", ""),
        "ENHANCED_GENERAL_FEEDBACK": final.get("enhancement_summary", ""),
    }

    return {
        "analysisJson": [json.dumps(a)],
        "analysisJson2": [json.dumps(b)],
        "analysisJson3": [json.dumps(c)],
    }

# --- Pipeline job orchestrator for Gumloop parity ---

async def run_pipeline_job(job_id: str, params: Dict[str, Any]):
    try:
        job_storage[job_id]['state'] = 'RUNNING'
        start = PipelineStartParams(**params)
        pipeline_type = start.pipelineType or 'requirement-analysis'

        if pipeline_type == 'text-to-mermaid':
            # Minimal stub for canvas flow
            job_storage[job_id]['state'] = 'DONE'
            job_storage[job_id]['result'] = {
                "status": "success",
                "outputs": {
                    "output": json.dumps({"mermaid_syntax": "graph TD; A-->B;"})
                },
                "processed_timestamp": datetime.now().isoformat()
            }
            job_storage[job_id]['completed_at'] = datetime.now().isoformat()
            return

        # Determine inputs
        organization_id = start.organizationId or job_storage[job_id].get('organization_id') or 'default'
        original_requirement = start.requirement or ""
        system_name = start.systemName or ""
        objective = start.objective or ""
        temperature = start.temperature or 0.1
        regulation_document_name = None
        if start.fileNames and len(start.fileNames) > 0:
            regulation_document_name = start.fileNames[0]
        else:
            regulation_document_name = ""

        # Step 1
        analysis_json = await analyze_requirement_step1(
            original_requirement, system_name, objective, "", temperature
        )

        # Step 2 (optional)
        try:
            if regulation_document_name:
                regulation_text = await get_regulation_document(regulation_document_name, organization_id)
                analysis_json2 = await analyze_regulation_step2(
                    analysis_json, regulation_text, regulation_document_name, temperature
                )
            else:
                analysis_json2 = {
                    "regulation_document": regulation_document_name or "",
                    "relevant_passages": [],
                    "compliance_concerns": [],
                    "regulatory_keywords": [],
                    "analysis_timestamp": datetime.now().isoformat()
                }
        except FileNotFoundError:
            analysis_json2 = {
                "regulation_document": regulation_document_name or "",
                "relevant_passages": [],
                "compliance_concerns": ["No regulation document found for analysis"],
                "regulatory_keywords": [],
                "analysis_timestamp": datetime.now().isoformat()
            }

        # Step 3
        analysis_json3 = await analyze_compliance_step3(
            analysis_json, analysis_json2, temperature
        )

        response_data = {
            "status": "success",
            "analysisJson": analysis_json,
            "analysisJson2": analysis_json2,
            "analysisJson3": analysis_json3,
            "processed_timestamp": datetime.now().isoformat()
        }

        job_storage[job_id]['state'] = 'DONE'
        job_storage[job_id]['result'] = response_data
        job_storage[job_id]['completed_at'] = datetime.now().isoformat()
    except Exception as e:
        logger.error(f"Pipeline job {job_id} failed: {str(e)}")
        job_storage[job_id]['state'] = 'FAILED'
        job_storage[job_id]['error'] = str(e)
        job_storage[job_id]['completed_at'] = datetime.now().isoformat()

# --- API Endpoints ---

@app.get(
    "/health", 
    tags=["System Health"],
    summary="Health Check",
    description="Check if the API service is running and healthy",
    responses={
        200: {
            "description": "Service is healthy",
            "content": {
                "application/json": {
                    "example": {
                        "status": "healthy",
                        "timestamp": "2025-07-30T23:46:19.318168"
                    }
                }
            }
        }
    }
)
async def health_check():
    """
    **Health Check Endpoint**
    
    Returns the current status of the API service along with a timestamp.
    This endpoint requires no authentication and can be used for monitoring and load balancer health checks.
    
    **Returns:**
    - `status`: Always "healthy" when the service is running
    - `timestamp`: ISO formatted timestamp of when the check was performed
    """
    return {"status": "healthy", "timestamp": datetime.now().isoformat()}

@app.post(
    "/analyze-requirement", 
    response_model=AnalysisResult, 
    tags=["Requirements Analysis"],
    summary="Analyze Requirements (Synchronous)",
    description="Perform complete requirements analysis against INCOSE/EARS standards and regulatory compliance",
    responses={
        200: {
            "description": "Analysis completed successfully",
            "content": {
                "application/json": {
                    "example": {
                        "status": "success",
                        "organizationId": "atoms-tech",
                        "analysisJson": {
                            "req_id": "REQ-001",
                            "original_requirement": "The system shall respond within 2 seconds",
                            "incose_format": "The system shall respond to user requests within 2 seconds of input submission.",
                            "ears_format": "When a user submits a request, the system shall respond within 2 seconds.",
                            "quality_rating": "8"
                        },
                        "processed_timestamp": "2025-07-30T23:46:19.318168"
                    }
                }
            }
        },
        422: {"description": "Validation Error"},
        500: {"description": "Internal Server Error"}
    }
)
async def analyze_requirement_sync(req: AnalysisRequest):
    """
    **Synchronous Requirements Analysis**
    
    Performs a complete three-step analysis of a software requirement:
    
    1. **INCOSE/EARS Analysis**: Evaluates requirement against industry standards
    2. **Regulatory Research**: Searches uploaded regulation documents for relevant clauses
    3. **Compliance Integration**: Produces enhanced, compliant requirements
    
    **Process:**
    - Analyzes requirement structure and clarity
    - Identifies violations of INCOSE and EARS standards
    - Rewrites requirement in proper format
    - Searches regulation documents for relevant passages
    - Provides final compliant requirement with traceability
    
    **Requirements:**
    - Valid organization ID with uploaded regulation documents
    - Gemini API key configured in environment
    - Proper authentication headers
    
    **Returns:**
    Complete analysis results including original analysis, regulatory findings, and final enhanced requirements.
    """
    try:
        logger.info(f"Starting analysis for requirement: {req.original_requirement[:50]}...")
        
        analysis_json = await analyze_requirement_step1(
            req.original_requirement, req.system_name, req.objective, req.req_id, req.temperature
        )
        
        try:
            regulation_text = await get_regulation_document(req.regulation_document_name, req.organizationId)
            analysis_json2 = await analyze_regulation_step2(
                analysis_json, regulation_text, req.regulation_document_name, req.temperature
            )
        except FileNotFoundError:
            analysis_json2 = {
                "regulation_document": req.regulation_document_name,
                "relevant_passages": [],
                "compliance_concerns": ["No regulation document found for analysis"],
                "regulatory_keywords": [],
                "analysis_timestamp": datetime.now().isoformat()
            }
        
        analysis_json3 = await analyze_compliance_step3(
            analysis_json, analysis_json2, req.temperature
        )
        
        response_data = {
            "status": "success",
            "organizationId": req.organizationId,
            "analysisJson": analysis_json,
            "analysisJson2": analysis_json2, 
            "analysisJson3": analysis_json3,
            "processed_timestamp": datetime.now().isoformat()
        }
        
        logger.info("Analysis completed successfully")
        return response_data
        
    except json.JSONDecodeError as e:
        raise HTTPException(status_code=500, detail=f"Invalid JSON in AI response: {str(e)}")
    except Exception as e:
        logger.error(f"Unexpected error: {str(e)}\n{traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")

@app.get(
    "/api/organizations/{organization_id}/documents", 
    tags=["Document Management"],
    summary="List Organization Documents",
    description="Retrieve all uploaded documents for a specific organization",
    responses={
        200: {
            "description": "List of documents retrieved successfully",
            "content": {
                "application/json": {
                    "example": {
                        "organizationId": "atoms-tech",
                        "documents": [
                            {
                                "name": "ISO_27001.pdf",
                                "size": 2048576,
                                "created": "2025-07-30T10:00:00.000Z",
                                "updated": "2025-07-30T10:00:00.000Z"
                            }
                        ],
                        "count": 1
                    }
                }
            }
        },
        404: {"description": "Organization not found"},
        500: {"description": "Internal Server Error"}
    }
)
async def list_documents(organization_id: str):
    """
    **List Organization Documents**
    
    Retrieves all regulation documents uploaded for the specified organization.
    Documents are stored in organization-specific Cloud Storage buckets.
    
    **Parameters:**
    - `organization_id`: Unique identifier for the organization
    
    **Returns:**
    - List of documents with metadata (name, size, timestamps)
    - Total count of documents
    - Organization ID for verification
    
    **Document Storage:**
    - Each organization has an isolated storage bucket
    - Only PDF documents are accepted
    - Automatic versioning for duplicate filenames
    """
    documents = await list_organization_documents(organization_id)
    return {
        "organizationId": organization_id,
        "documents": documents,
        "count": len(documents)
    }

@app.post(
    "/api/organizations/{organization_id}/documents", 
    tags=["Document Management"],
    summary="Upload Organization Documents",
    description="Upload PDF regulation documents to an organization's secure storage",
    responses={
        200: {
            "description": "Documents uploaded successfully",
            "content": {
                "application/json": {
                    "example": {
                        "organizationId": "atoms-tech",
                        "files": ["ISO_27001.pdf", "GDPR_regulation.pdf"],
                        "message": "Successfully uploaded 2 files"
                    }
                }
            }
        },
        400: {"description": "Invalid file format (only PDF allowed)"},
        500: {"description": "Upload failed"}
    }
)
async def upload_organization_documents(organization_id: str, files: List[UploadFile] = File(...)):
    """
    **Upload Organization Documents**
    
    Upload regulation documents (PDFs only) to the organization's secure storage bucket.
    These documents will be used for regulatory compliance analysis.
    
    **Parameters:**
    - `organization_id`: Unique identifier for the organization
    - `files`: One or more PDF files to upload
    
    **File Requirements:**
    - Must be PDF format (.pdf extension)
    - Reasonable file size limits apply
    - Duplicate filenames are automatically versioned
    
    **Security:**
    - Each organization has isolated storage
    - Files are securely stored in Google Cloud Storage
    - Access controlled by organization membership
    
    **Returns:**
    - List of successfully uploaded filenames
    - Upload confirmation message
    - Organization ID for verification
    """
    uploaded_files = []
    for file in files:
        if not file.filename.lower().endswith('.pdf'):
            raise HTTPException(status_code=400, detail=f"Only PDF files are allowed. Got: {file.filename}")
        
        file_content = await file.read()
        final_filename = await upload_file_to_organization_bucket(file_content, file.filename, organization_id)
        uploaded_files.append(final_filename)
    
    logger.info(f"Successfully uploaded {len(uploaded_files)} files to organization {organization_id}")
    return {
        "organizationId": organization_id,
        "files": uploaded_files, 
        "message": f"Successfully uploaded {len(uploaded_files)} files"
    }

@app.delete(
    "/api/organizations/{organization_id}/documents/{document_name}", 
    tags=["Document Management"],
    summary="Delete Organization Document",
    description="Permanently delete a regulation document from organization storage",
    responses={
        200: {
            "description": "Document deleted successfully",
            "content": {
                "application/json": {
                    "example": {
                        "organizationId": "atoms-tech",
                        "document": "ISO_27001.pdf",
                        "message": "Document deleted successfully"
                    }
                }
            }
        },
        404: {"description": "Document or organization not found"},
        500: {"description": "Delete operation failed"}
    }
)
async def delete_document(organization_id: str, document_name: str):
    """
    **Delete Organization Document**
    
    Permanently removes a regulation document from the organization's storage.
    This action cannot be undone.
    
    **Parameters:**
    - `organization_id`: Unique identifier for the organization
    - `document_name`: Exact filename of the document to delete
    
    **Security:**
    - Only documents belonging to the specified organization can be deleted
    - Requires proper authentication and organization membership
    - Action is logged for audit purposes
    
    **Warning:**
    Deleting a document may affect ongoing or future requirements analysis
    that depends on that regulation document.
    
    **Returns:**
    - Confirmation of successful deletion
    - Organization and document identifiers
    """
    await delete_organization_document(organization_id, document_name)
    return {
        "organizationId": organization_id,
        "document": document_name,
        "message": "Document deleted successfully"
    }

@app.post(
    "/api/upload", 
    tags=["Document Management (Legacy)"],
    summary="Upload Documents (Legacy)",
    description="Legacy endpoint for uploading documents. Use /api/organizations/{id}/documents instead.",
    deprecated=True,
    responses={
        200: {"description": "Documents uploaded successfully"},
        400: {"description": "Invalid file format"},
        500: {"description": "Upload failed"}
    }
)
async def upload_files_legacy(organizationId: str = Form(...), files: List[UploadFile] = File(...)):
    """
    **Legacy File Upload Endpoint**
    
    ⚠️ **DEPRECATED**: This endpoint is maintained for backward compatibility only.
    
    **Recommended Alternative:**
    Use `POST /api/organizations/{organization_id}/documents` instead.
    
    **Functionality:**
    Same as the modern upload endpoint but uses form parameters instead of URL path.
    
    **Migration:**
    Replace calls to this endpoint with the new document management endpoints
    for better REST compliance and improved functionality.
    """
    return await upload_organization_documents(organizationId, files)

@app.post(
    "/api/ai", 
    tags=["Requirements Analysis"],
    summary="Start Analysis Pipeline (Asynchronous)",
    description="Start a requirements analysis job that runs in the background",
    responses={
        200: {"description": "Analysis pipeline started successfully"},
        422: {"description": "Validation Error"},
        500: {"description": "Failed to start pipeline"}
    }
)
async def start_pipeline(req: PipelineStartParams, background_tasks: BackgroundTasks):
    job_id = str(uuid.uuid4())
    job_storage[job_id] = {
        'state': 'QUEUED',
        'started_at': datetime.now().isoformat(),
        'organization_id': getattr(req, 'organizationId', None)
    }
    background_tasks.add_task(run_pipeline_job, job_id, req.dict())
    return {
        "run_id": job_id,
        "useRegulation": False
    }

@app.get(
    "/api/ai", 
    tags=["Requirements Analysis"],
    summary="Get Analysis Pipeline Status",
    description="Check the status and retrieve results of an asynchronous analysis job",
)
async def get_pipeline_status(runId: str, organizationId: str = None):
    if runId not in job_storage:
        raise HTTPException(status_code=404, detail=json.dumps({"error": "Job not found"}))
    job = job_storage[runId]
    response: Dict[str, Any] = {
        "run_id": runId,
        "state": job['state'],
        "credit_cost": 0,
    }
    if job['state'] == 'DONE':
        result = job.get('result', {})
        # If text-to-mermaid stub present
        outputs = result.get("outputs")
        if outputs and "output" in outputs:
            response["outputs"] = outputs
        else:
            response["outputs"] = _build_legacy_outputs(result)
    elif job['state'] == 'FAILED':
        response['error'] = job.get('error')
    return response

# --- Upload compatibility route ---

@app.post(
    "/api/upload",
    tags=["Document Management (Compatibility)"],
    summary="Upload Documents (Compatibility)",
    description="Accepts multipart/form-data with 'files' only. Optional organizationId can be passed as a form field; if omitted, uses a default bucket.",
)
async def upload_files_compat(files: List[UploadFile] = File(...), organizationId: str = Form(None)):
    org = organizationId or "default"
    uploaded_files = []
    for file in files:
        if not (file.filename.lower().endswith('.pdf') or file.filename.lower().endswith('.md')):
            raise HTTPException(status_code=400, detail=json.dumps({"error": f"Invalid file type: {file.filename}"}))
        content = await file.read()
        # store as-is; content type pdf or markdown
        final_filename = await upload_file_to_organization_bucket(content, file.filename, org)
        uploaded_files.append(final_filename)
    return {"success": True, "files": uploaded_files}

# --- New Requirements Endpoints ---

@app.post(
    "/api/requirements",
    tags=["Requirements"],
    summary="Create requirement (sync analysis and persist)",
    response_model=RequirementRecord,
    responses={
        200: {
            "description": "Requirement created",
            "content": {
                "application/json": {
                    "example": {
                        "req_id": "0001",
                                "organizationId": "atoms-tech",
                        "final_requirement_ears": "When a valid user input...",
                        "final_requirement_incose": "The system shall respond...",
                        "compliance_status": "COMPLIANT",
                        "final_quality_rating": "9",
                        "enhancement_summary": "Specified timing and method",
                        "created_at": "2025-08-29T18:00:00.000Z",
                        "input_source": "text",
                        "document_name": None
                    }
                }
            }
        },
        400: {"description": "Bad Request"},
        500: {"description": "Server Error"}
    }
)
async def create_requirement(payload: RequirementCreateRequest) -> RequirementRecord:
    try:
        organization_id = payload.organizationId
        if not organization_id:
            raise HTTPException(status_code=400, detail=json.dumps({"error": "organizationId is required"}))
        original_requirement = payload.original_requirement or ""
        system_name = payload.systemName or ""
        objective = payload.objective or ""
        regulation_document_name = payload.regulation_document_name or ""
        temperature = float(payload.temperature or 0.1)

        # Generate new req_id
        req_id = next_req_id(organization_id)

        # Persist input if text provided
        if original_requirement:
            await _persist_input_json(organization_id, req_id, {
                "organizationId": organization_id,
                "req_id": req_id,
                "original_requirement": original_requirement,
                "system_name": system_name,
                "objective": objective,
                "regulation_document_name": regulation_document_name,
                "created_at": datetime.now().isoformat(),
                "input_source": "text"
            })

        # Run analysis synchronously
        analysis_json = await analyze_requirement_step1(original_requirement, system_name, objective, req_id, temperature)
        if regulation_document_name:
            try:
                regulation_text = await get_regulation_document(regulation_document_name, organization_id)
                analysis_json2 = await analyze_regulation_step2(analysis_json, regulation_text, regulation_document_name, temperature)
            except FileNotFoundError:
                analysis_json2 = {
                    "regulation_document": regulation_document_name,
                    "relevant_passages": [],
                    "compliance_concerns": ["No regulation document found for analysis"],
                    "regulatory_keywords": [],
                    "analysis_timestamp": datetime.now().isoformat()
                }
        else:
            analysis_json2 = {
                "regulation_document": "",
                "relevant_passages": [],
                "compliance_concerns": [],
                "regulatory_keywords": [],
                "analysis_timestamp": datetime.now().isoformat()
            }
        analysis_json3 = await analyze_compliance_step3(analysis_json, analysis_json2, temperature)

        record: RequirementRecord = RequirementRecord(
            req_id=req_id,
            organizationId=organization_id,
            final_requirement_ears=analysis_json3.get("final_requirement_ears", ""),
            final_requirement_incose=analysis_json3.get("final_requirement_incose", ""),
            compliance_status=analysis_json3.get("compliance_status", ""),
            final_quality_rating=str(analysis_json3.get("final_quality_rating", "")),
            enhancement_summary=analysis_json3.get("enhancement_summary", ""),
            created_at=datetime.now().isoformat(),
            input_source="text" if original_requirement else "pdf",
            document_name=regulation_document_name or None
        )
        await _persist_requirement_json(organization_id, req_id, record.model_dump())
        return record
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Create requirement failed: {e}")
        raise HTTPException(status_code=500, detail=json.dumps({"error": "Failed to create requirement"}))

@app.post(
    "/api/requirements",
    tags=["Requirements"],
    summary="Create requirement",
    response_model=RequirementRecord,
)
async def create_requirement(payload: RequirementCreateRequest) -> RequirementRecord:
    try:
        organization_id = payload.organizationId
        if not organization_id:
            raise HTTPException(status_code=400, detail=json.dumps({"error": "organizationId is required"}))
        original_requirement = payload.original_requirement or ""
        system_name = payload.systemName or ""
        objective = payload.objective or ""
        regulation_document_name = payload.regulation_document_name or ""
        temperature = float(payload.temperature or 0.1)

        # Generate new req_id
        req_id = next_req_id(organization_id)

        # Persist input if text provided
        if original_requirement:
            await _persist_input_json(organization_id, req_id, {
                "organizationId": organization_id,
                "req_id": req_id,
                "original_requirement": original_requirement,
                "system_name": system_name,
                "objective": objective,
                "regulation_document_name": regulation_document_name,
                "created_at": datetime.now().isoformat(),
                "input_source": "text"
            })

        # Run analysis synchronously
        analysis_json = await analyze_requirement_step1(original_requirement, system_name, objective, req_id, temperature)
        if regulation_document_name:
            try:
                regulation_text = await get_regulation_document(regulation_document_name, organization_id)
                analysis_json2 = await analyze_regulation_step2(analysis_json, regulation_text, regulation_document_name, temperature)
            except FileNotFoundError:
                analysis_json2 = {
                    "regulation_document": regulation_document_name,
                    "relevant_passages": [],
                    "compliance_concerns": ["No regulation document found for analysis"],
                    "regulatory_keywords": [],
                    "analysis_timestamp": datetime.now().isoformat()
                }
        else:
            analysis_json2 = {
                "regulation_document": "",
                "relevant_passages": [],
                "compliance_concerns": [],
                "regulatory_keywords": [],
                "analysis_timestamp": datetime.now().isoformat()
            }
        analysis_json3 = await analyze_compliance_step3(analysis_json, analysis_json2, temperature)

        record: RequirementRecord = RequirementRecord(
            req_id=req_id,
            organizationId=organization_id,
            final_requirement_ears=analysis_json3.get("final_requirement_ears", ""),
            final_requirement_incose=analysis_json3.get("final_requirement_incose", ""),
            compliance_status=analysis_json3.get("compliance_status", ""),
            final_quality_rating=str(analysis_json3.get("final_quality_rating", "")),
            enhancement_summary=analysis_json3.get("enhancement_summary", ""),
            created_at=datetime.now().isoformat(),
            input_source="text" if original_requirement else "pdf",
            document_name=regulation_document_name or None
        )
        await _persist_requirement_json(organization_id, req_id, record.model_dump())
        return record
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Create requirement failed: {e}")
        raise HTTPException(status_code=500, detail=json.dumps({"error": "Failed to create requirement"}))

@app.get(
    "/api/requirements",
    tags=["Requirements"],
    summary="List requirements",
    response_model=RequirementListResponse,
)
async def list_requirements(organizationId: str = Query(..., examples=["atoms-tech"]), page: int = Query(1, ge=1), pageSize: int = Query(20, ge=1, le=100)) -> RequirementListResponse:
    try:
        data = await _list_requirements(organizationId, page, pageSize)
        return RequirementListResponse(**data)
    except Exception as e:
        logger.error(f"List requirements failed: {e}")
        raise HTTPException(status_code=500, detail=json.dumps({"error": "Failed to list requirements"}))

@app.get(
    "/api/requirements/{reqId}",
    tags=["Requirements"],
    summary="Get requirement",
    response_model=RequirementRecord,
)
async def get_requirement(reqId: str = FPath(..., examples=["0001"]), organizationId: str = Query(..., examples=["atoms-tech"])) -> RequirementRecord:
    try:
        data = await _get_requirement_json(organizationId, reqId)
        return RequirementRecord(**data)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=json.dumps({"error": "Requirement not found"}))
    except Exception as e:
        logger.error(f"Get requirement failed: {e}")
        raise HTTPException(status_code=500, detail=json.dumps({"error": "Failed to get requirement"}))

class RefineBody(BaseModel):
    model_config = ConfigDict(json_schema_extra={
        "example": {
            "pipelineType": "requirement-analysis",
            "requirement": "The system shall respond within 2 seconds",
            "systemName": "Web",
            "objective": "Performance"
        }
    })
    userId: str | None = None
    pipelineType: str | None = Field(default="requirement-analysis")
    requirement: str
    file_urls: List[str] | None = None
    systemName: str | None = None
    objective: str | None = None
    temperature: float | None = None

class RefineAndSaveBody(RefineBody):
    model_config = ConfigDict(json_schema_extra={
        "example": {
            "pipelineType": "requirement-analysis",
            "requirement": "The system shall respond within 2 seconds",
            "systemName": "Web",
            "objective": "Performance",
            "document_id": "0885a911-26dc-4623-9b27-dcdcb624da8f",
            "block_id": "88f46695-ae65-4d93-98c2-88dabba2c94b",
            "name": "Login responds within 2s",
            "original_requirement": "The system shall respond within 2 seconds",
            "tags": ["performance"]
        }
    })
    document_id: str
    block_id: str
    name: str
    original_requirement: str | None = None
    description: str | None = None
    created_by: str | None = None
    tags: List[str] | None = None

@app.post("/v1/agent/refine", tags=["Agent"], summary="Refine requirement (proxy)")
async def proxy_refine(body: RefineBody):
    try:
        r = agent_refine(
            requirement=body.requirement,
            systemName=body.systemName or "",
            objective=body.objective or "",
            file_urls=body.file_urls or None,
        )
        # Present as DONE payload for FE parity
        return {
            "run_id": r.get("run_id"),
            "state": "DONE",
            "outputs": r.get("outputs", {}),
            "credit_cost": 0,
        }
    except ValueError as e:
        logger.error(f"proxy_refine_validation_failed: {e}")
        raise HTTPException(status_code=400, detail=json.dumps({"error": "VALIDATION_ERROR", "message": str(e)}))
    except Exception as e:
        logger.error(f"proxy_refine_failed: {e}")
        raise HTTPException(status_code=500, detail=json.dumps({"error": "MODEL_ERROR"}))

@app.post("/v1/agent/refine-and-save", tags=["Agent"], summary="Refine and save to Supabase (proxy)")
async def proxy_refine_and_save(body: RefineAndSaveBody):
    try:
        r = agent_refine(
            requirement=body.requirement,
            systemName=body.systemName or "",
            objective=body.objective or "",
            file_urls=body.file_urls or None,
        )
        saved = agent_save(
            document_id=body.document_id,
            block_id=body.block_id,
            name=body.name,
            final_requirement_incose=r["analysisJson3"].get("final_requirement_incose", ""),
            final_requirement_ears=r["analysisJson3"].get("final_requirement_ears", ""),
            compliance_status=r["analysisJson3"].get("compliance_status", ""),
            final_quality_rating=r["analysisJson3"].get("final_quality_rating", None),
            regulatory_traceability=r["analysisJson2"].get("relevant_passages", []),
            original_requirement=body.original_requirement,
            description=body.description,
            created_by=body.created_by,
            tags=body.tags or [],
        )
        return {
            "run_id": r.get("run_id"),
            "state": "DONE",
            "outputs": r.get("outputs", {}),
            "save": saved,
            "credit_cost": 0,
        }
    except ValueError as e:
        logger.error(f"proxy_refine_and_save_validation_failed: {e}")
        raise HTTPException(status_code=400, detail=json.dumps({"error": "VALIDATION_ERROR", "message": str(e)}))
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"proxy_refine_and_save_failed: {e}")
        raise HTTPException(status_code=500, detail=json.dumps({"error": "MODEL_OR_DB_ERROR"}))

if __name__ == "__main__":
    import uvicorn
    required_env_vars = ['GEMINI_API_KEY']
    missing_vars = [var for var in required_env_vars if not os.getenv(var)]
    if missing_vars:
        logger.error(f"Missing required environment variables: {missing_vars}")
        exit(1)
    
    port = int(os.getenv("PORT", 8080))
    uvicorn.run(app, host="0.0.0.0", port=port)
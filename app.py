import os
import json
import logging
from datetime import datetime
from fastapi import FastAPI, HTTPException, BackgroundTasks, File, UploadFile, Form
from fastapi.middleware.cors import CORSMiddleware
from typing import List, Dict, Any
import google.generativeai as genai
from google.cloud import storage
import PyPDF2
from io import BytesIO
import traceback
import uuid
from werkzeug.utils import secure_filename
import re

# Import Pydantic models
from models import AnalysisRequest, PipelineRequest, AnalysisResult

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
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize Google AI
if os.getenv('GEMINI_API_KEY'):
    genai.configure(api_key=os.getenv('GEMINI_API_KEY'))

# Initialize Google Cloud Storage client
storage_client = storage.Client()

# In-memory job storage (in production, use Redis or database)
job_storage: Dict[str, Dict[str, Any]] = {}

# --- Helper Functions ---

def get_organization_bucket_name(organization_id: str) -> str:
    """Get bucket name for organization."""
    return f"{organization_id}-requirements"

def create_bucket_if_not_exists(bucket_name: str) -> storage.Bucket:
    """Create bucket if it doesn't exist."""
    try:
        bucket = storage_client.bucket(bucket_name)
        if not bucket.exists():
            bucket = storage_client.create_bucket(bucket_name, location="US")
            logger.info(f"Created bucket: {bucket_name}")
        return bucket
    except Exception as e:
        logger.error(f"Error creating bucket {bucket_name}: {str(e)}")
        raise

def get_versioned_filename(bucket: storage.Bucket, base_filename: str) -> str:
    """Get a versioned filename if the base filename already exists."""
    name, ext = os.path.splitext(base_filename)
    blob = bucket.blob(base_filename)
    if not blob.exists():
        return base_filename
    
    counter = 1
    while True:
        versioned_name = f"{name}({counter}){ext}"
        blob = bucket.blob(versioned_name)
        if not blob.exists():
            return versioned_name
        counter += 1

async def list_organization_documents(organization_id: str) -> List[Dict[str, Any]]:
    """List all documents in an organization's bucket."""
    try:
        bucket_name = get_organization_bucket_name(organization_id)
        bucket = storage_client.bucket(bucket_name)
        
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
        bucket = storage_client.bucket(bucket_name)
        
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
    try:
        bucket_name = get_organization_bucket_name(organization_id)
        bucket = storage_client.bucket(bucket_name)
        
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
    prompt = f"""
    As a requirements engineering expert, analyze the following requirement against INCOSE and EARS (Easy Approach to Requirements Syntax) standards.

    System Name: {system_name}
    Objective: {objective}
    Original Requirement: {original_requirement}
    REQ-ID: {req_id}

    Please provide a comprehensive analysis that includes:

    1. INCOSE Format Analysis:
       - Rewrite the requirement following INCOSE best practices
       - Identify any INCOSE rule violations
       - Provide feedback on clarity, completeness, and correctness

    2. EARS Format Analysis:
       - Rewrite the requirement in EARS format (When <trigger>, the <system> shall <response>)
       - Identify the trigger, system, and response components
       - Provide feedback on EARS compliance

    3. Structured Analysis:
       - Extract/assign REQ_ID if not provided
       - Identify requirement patterns (functional, performance, interface, etc.)
       - List specific violations and recommendations
       - Rate the requirement quality (1-10 scale)

    Return your response as a valid JSON object with the following structure:
    {{
        "req_id": "extracted or provided REQ_ID",
        "original_requirement": "the original requirement text",
        "incose_format": "requirement rewritten in INCOSE format",
        "ears_format": "requirement rewritten in EARS format", 
        "incose_violations": ["list of INCOSE violations found"],
        "ears_violations": ["list of EARS violations found"],
        "requirement_pattern": "functional/performance/interface/etc",
        "quality_rating": "1-10 rating",
        "feedback": "detailed feedback and recommendations",
        "analysis_timestamp": "{datetime.now().isoformat()}"
    }}
    """
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
    prompt = f"""
    As a regulatory compliance expert, analyze the following requirement against the provided regulation document.

    Requirement Analysis from Step 1:
    {json.dumps(requirement_analysis, indent=2)}

    Regulation Document: {regulation_doc_name}
    Regulation Text: {regulation_text[:10000]}...  # Truncate for context limit

    Tasks:
    1. Search through the regulation text for passages relevant to this requirement
    2. Identify specific regulatory clauses, sections, or standards that apply
    3. Extract relevant regulatory text that could impact the requirement
    4. Assess potential compliance issues or conflicts

    Return your response as a valid JSON object with the following structure:
    {{
        "regulation_document": "{regulation_doc_name}",
        "relevant_passages": [
            {{
                "section": "section/clause identifier",
                "text": "relevant regulatory text",
                "relevance_score": "1-10 how relevant this passage is",
                "impact": "description of how this impacts the requirement"
            }}
        ],
        "compliance_concerns": ["list of potential compliance issues"],
        "regulatory_keywords": ["key terms found in regulation relevant to requirement"],
        "analysis_timestamp": "{datetime.now().isoformat()}"
    }}
    """
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
    prompt = f"""
    As a systems engineering expert, integrate the requirement analysis with regulatory findings to produce enhanced, compliant requirements.

    Requirement Analysis (Step 1):
    {json.dumps(requirement_analysis, indent=2)}

    Regulatory Analysis (Step 2): 
    {json.dumps(regulation_analysis, indent=2)}

    Tasks:
    1. Combine requirement analysis with regulatory findings
    2. Identify conflicts between the requirement and regulations
    3. Produce enhanced versions that comply with both EARS/INCOSE standards AND regulations
    4. Provide final compliance feedback and recommendations
    5. Create a final requirement that satisfies all standards

    Return your response as a valid JSON object with the following structure:
    {{
        "final_requirement_ears": "final requirement in EARS format with regulatory compliance",
        "final_requirement_incose": "final requirement in INCOSE format with regulatory compliance", 
        "compliance_status": "COMPLIANT/NON_COMPLIANT/PARTIAL",
        "identified_conflicts": ["list of conflicts between requirement and regulations"],
        "resolution_strategies": ["strategies to resolve conflicts"],
        "compliance_recommendations": ["specific recommendations for full compliance"],
        "regulatory_traceability": ["list of regulatory sections this requirement traces to"],
        "final_quality_rating": "1-10 rating for the enhanced requirement",
        "enhancement_summary": "summary of improvements made to achieve compliance",
        "analysis_timestamp": "{datetime.now().isoformat()}"
    }}
    """
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
        200: {
            "description": "Analysis pipeline started successfully",
            "content": {
                "application/json": {
                    "example": {
                        "runId": "550e8400-e29b-41d4-a716-446655440000",
                        "organizationId": "atoms-tech",
                        "state": "QUEUED",
                        "message": "Analysis pipeline started successfully"
                    }
                }
            }
        },
        422: {"description": "Validation Error"},
        500: {"description": "Failed to start pipeline"}
    }
)
async def start_pipeline(req: PipelineRequest, background_tasks: BackgroundTasks):
    """
    **Start Asynchronous Analysis Pipeline**
    
    Initiates a background analysis job for requirements processing. This is useful for:
    - Processing multiple requirements
    - Long-running analysis tasks
    - Integration with external workflow systems
    
    **Process:**
    1. Validates input parameters
    2. Creates a unique job ID
    3. Queues the analysis job
    4. Returns immediately with job ID
    
    **Use Cases:**
    - Batch processing of requirements
    - Integration with Gumloop or similar platforms
    - When immediate response is not required
    
    **Returns:**
    - `runId`: Unique identifier to track job progress
    - `state`: Initial state (always "QUEUED")
    - Organization ID for verification
    
    **Next Steps:**
    Use the GET /api/ai endpoint with the returned `runId` to check progress and retrieve results.
    """
    job_id = str(uuid.uuid4())
    job_storage[job_id] = {
        'state': 'QUEUED',
        'started_at': datetime.now().isoformat(),
        'organization_id': req.organizationId
    }
    
    background_tasks.add_task(run_analysis_job, job_id, req.dict())
    
    return {
        "runId": job_id,
        "organizationId": req.organizationId,
        "state": "QUEUED",
        "message": "Analysis pipeline started successfully"
    }

@app.get(
    "/api/ai", 
    tags=["Requirements Analysis"],
    summary="Get Analysis Pipeline Status",
    description="Check the status and retrieve results of an asynchronous analysis job",
    responses={
        200: {
            "description": "Pipeline status retrieved successfully",
            "content": {
                "application/json": {
                    "examples": {
                        "running": {
                            "summary": "Job in progress",
                            "value": {
                                "runId": "550e8400-e29b-41d4-a716-446655440000",
                                "organizationId": "atoms-tech",
                                "state": "RUNNING",
                                "started_at": "2025-07-30T23:46:19.318168"
                            }
                        },
                        "completed": {
                            "summary": "Job completed",
                            "value": {
                                "runId": "550e8400-e29b-41d4-a716-446655440000",
                                "organizationId": "atoms-tech",
                                "state": "DONE",
                                "started_at": "2025-07-30T23:46:19.318168",
                                "completed_at": "2025-07-30T23:47:25.123456",
                                "result": {
                                    "status": "success",
                                    "analysisJson": "...",
                                    "analysisJson2": "...",
                                    "analysisJson3": "..."
                                }
                            }
                        }
                    }
                }
            }
        },
        404: {"description": "Job not found"},
        500: {"description": "Internal Server Error"}
    }
)
async def get_pipeline_status(runId: str, organizationId: str = None):
    """
    **Get Analysis Pipeline Status**
    
    Retrieves the current status and results of an asynchronous analysis job.
    
    **Parameters:**
    - `runId`: Unique job identifier from the POST /api/ai response
    - `organizationId`: Optional organization ID for additional verification
    
    **Job States:**
    - `QUEUED`: Job is waiting to be processed
    - `RUNNING`: Job is currently being processed
    - `DONE`: Job completed successfully with results available
    - `FAILED`: Job failed with error details available
    
    **Polling:**
    - Check status periodically until state is DONE or FAILED
    - Typical processing time: 30-60 seconds per requirement
    - Results are cached for 24 hours after completion
    
    **Returns:**
    - Current job state and timestamps
    - Complete analysis results when DONE
    - Error details when FAILED
    """
    if runId not in job_storage:
        raise HTTPException(status_code=404, detail="Job not found")
    
    job = job_storage[runId]
    response = {
        "runId": runId,
        "organizationId": organizationId or job.get('organization_id', 'default'),
        "state": job['state'],
        "started_at": job.get('started_at'),
        "completed_at": job.get('completed_at')
    }
    
    if job['state'] == 'DONE':
        response['result'] = job.get('result')
    elif job['state'] == 'FAILED':
        response['error'] = job.get('error')
    
    return response

if __name__ == "__main__":
    import uvicorn
    required_env_vars = ['GEMINI_API_KEY']
    missing_vars = [var for var in required_env_vars if not os.getenv(var)]
    if missing_vars:
        logger.error(f"Missing required environment variables: {missing_vars}")
        exit(1)
    
    port = int(os.getenv("PORT", 8080))
    uvicorn.run(app, host="0.0.0.0", port=port)
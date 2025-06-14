import os
import json
import logging
from datetime import datetime
from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
import google.generativeai as genai
from google.cloud import storage
from google.oauth2 import service_account
import PyPDF2
from io import BytesIO
import traceback
import yaml
import uuid
import threading
from werkzeug.utils import secure_filename
import re

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)
CORS(app)  # Enable CORS for all routes

# Initialize Google AI
genai.configure(api_key=os.getenv('GEMINI_API_KEY'))

# Initialize Google Cloud Storage client
storage_client = storage.Client()

# In-memory job storage (in production, use Redis or database)
job_storage = {}

def get_organization_bucket_name(organization_id):
    """Get bucket name for organization."""
    return f"{organization_id}-requirements"

def create_bucket_if_not_exists(bucket_name):
    """Create bucket if it doesn't exist."""
    try:
        bucket = storage_client.bucket(bucket_name)
        if not bucket.exists():
            # Create bucket in the same region as the service
            bucket = storage_client.create_bucket(bucket_name, location="US")
            logger.info(f"Created bucket: {bucket_name}")
        return bucket
    except Exception as e:
        logger.error(f"Error creating bucket {bucket_name}: {str(e)}")
        raise

def get_versioned_filename(bucket, base_filename):
    """Get a versioned filename if the base filename already exists."""
    # Extract name and extension
    name, ext = os.path.splitext(base_filename)
    
    # Check if base filename exists
    blob = bucket.blob(base_filename)
    if not blob.exists():
        return base_filename
    
    # Find the next available version
    counter = 1
    while True:
        versioned_name = f"{name}({counter}){ext}"
        blob = bucket.blob(versioned_name)
        if not blob.exists():
            return versioned_name
        counter += 1

def list_organization_documents(organization_id):
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
        raise

def delete_organization_document(organization_id, document_name):
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
    except Exception as e:
        logger.error(f"Error deleting document {document_name} for organization {organization_id}: {str(e)}")
        raise

def extract_text_from_pdf(pdf_content):
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

def get_regulation_document(document_name, organization_id):
    """Download and extract text from regulation document in organization's bucket."""
    try:
        bucket_name = get_organization_bucket_name(organization_id)
        bucket = storage_client.bucket(bucket_name)
        
        if not bucket.exists():
            raise FileNotFoundError(f"Organization bucket not found: {bucket_name}")
        
        # Try different possible file extensions
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

def upload_file_to_organization_bucket(file_content, filename, organization_id):
    """Upload file to organization's Cloud Storage bucket."""
    try:
        bucket_name = get_organization_bucket_name(organization_id)
        bucket = create_bucket_if_not_exists(bucket_name)
        
        # Get versioned filename to handle duplicates
        secure_name = secure_filename(filename)
        final_filename = get_versioned_filename(bucket, secure_name)
        
        blob = bucket.blob(final_filename)
        blob.upload_from_string(file_content, content_type='application/pdf')
        
        logger.info(f"File {final_filename} uploaded to organization {organization_id} bucket")
        return final_filename
    except Exception as e:
        logger.error(f"Error uploading file: {str(e)}")
        raise

def analyze_requirement_step1(original_requirement, system_name="", objective="", req_id="", temperature=0.1):
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
        model = genai.GenerativeModel('gemini-2.0-flash-exp')
        response = model.generate_content(
            prompt,
            generation_config=genai.types.GenerationConfig(temperature=temperature)
        )
        
        # Extract JSON from response
        response_text = response.text.strip()
        if response_text.startswith('```json'):
            response_text = response_text[7:-3].strip()
        elif response_text.startswith('```'):
            response_text = response_text[3:-3].strip()
            
        return json.loads(response_text)
        
    except Exception as e:
        logger.error(f"Error in Step 1 analysis: {str(e)}")
        raise

def analyze_regulation_step2(requirement_analysis, regulation_text, regulation_doc_name, temperature=0.1):
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
        model = genai.GenerativeModel('gemini-2.0-flash-exp')
        response = model.generate_content(
            prompt,
            generation_config=genai.types.GenerationConfig(temperature=temperature)
        )
        
        # Extract JSON from response
        response_text = response.text.strip()
        if response_text.startswith('```json'):
            response_text = response_text[7:-3].strip()
        elif response_text.startswith('```'):
            response_text = response_text[3:-3].strip()
            
        return json.loads(response_text)
        
    except Exception as e:
        logger.error(f"Error in Step 2 analysis: {str(e)}")
        raise

def analyze_compliance_step3(requirement_analysis, regulation_analysis, temperature=0.1):
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
        model = genai.GenerativeModel('gemini-2.0-flash-exp')
        response = model.generate_content(
            prompt,
            generation_config=genai.types.GenerationConfig(temperature=temperature)
        )
        
        # Extract JSON from response
        response_text = response.text.strip()
        if response_text.startswith('```json'):
            response_text = response_text[7:-3].strip()
        elif response_text.startswith('```'):
            response_text = response_text[3:-3].strip()
            
        return json.loads(response_text)
        
    except Exception as e:
        logger.error(f"Error in Step 3 analysis: {str(e)}")
        raise

def run_analysis_job(job_id, analysis_params):
    """Run the analysis job in background thread."""
    try:
        logger.info(f"Starting analysis job {job_id}")
        job_storage[job_id]['state'] = 'RUNNING'
        
        # Extract parameters
        original_requirement = analysis_params['original_requirement']
        regulation_document_name = analysis_params['regulation_document_name']
        organization_id = analysis_params['organization_id']
        system_name = analysis_params.get('system_name', '')
        objective = analysis_params.get('objective', '')
        req_id = analysis_params.get('req_id', '')
        temperature = analysis_params.get('temperature', 0.1)
        
        # Step 1: Initial Requirements Analysis
        logger.info(f"Job {job_id}: Step 1 - Analyzing requirement against INCOSE/EARS standards")
        analysis_json = analyze_requirement_step1(
            original_requirement, system_name, objective, req_id, temperature
        )
        
        # Step 2: Regulatory Research
        logger.info(f"Job {job_id}: Step 2 - Analyzing regulatory compliance")
        try:
            regulation_text = get_regulation_document(regulation_document_name, organization_id)
            analysis_json2 = analyze_regulation_step2(
                analysis_json, regulation_text, regulation_document_name, temperature
            )
        except FileNotFoundError:
            # If no regulation document found, continue with empty regulatory analysis
            logger.warning(f"No regulation document found for organization {organization_id}, continuing without regulatory analysis")
            analysis_json2 = {
                "regulation_document": regulation_document_name,
                "relevant_passages": [],
                "compliance_concerns": ["No regulation document found for analysis"],
                "regulatory_keywords": [],
                "analysis_timestamp": datetime.now().isoformat()
            }
        
        # Step 3: Compliance Integration
        logger.info(f"Job {job_id}: Step 3 - Integrating compliance findings")
        analysis_json3 = analyze_compliance_step3(
            analysis_json, analysis_json2, temperature
        )
        
        # Prepare final response
        response_data = {
            "status": "success",
            "analysisJson": analysis_json,
            "analysisJson2": analysis_json2, 
            "analysisJson3": analysis_json3,
            "processed_timestamp": datetime.now().isoformat()
        }
        
        # Update job with results
        job_storage[job_id]['state'] = 'DONE'
        job_storage[job_id]['result'] = response_data
        job_storage[job_id]['completed_at'] = datetime.now().isoformat()
        
        logger.info(f"Analysis job {job_id} completed successfully")
        
    except Exception as e:
        logger.error(f"Job {job_id} failed: {str(e)}")
        job_storage[job_id]['state'] = 'FAILED'
        job_storage[job_id]['error'] = str(e)
        job_storage[job_id]['completed_at'] = datetime.now().isoformat()

# Document Management Endpoints

@app.route('/api/organizations/<organization_id>/documents', methods=['GET'])
def list_documents(organization_id):
    """List all documents for an organization."""
    try:
        documents = list_organization_documents(organization_id)
        return jsonify({
            "organizationId": organization_id,
            "documents": documents,
            "count": len(documents)
        })
        
    except Exception as e:
        logger.error(f"Error listing documents for organization {organization_id}: {str(e)}")
        return jsonify({"error": f"Failed to list documents: {str(e)}"}), 500

@app.route('/api/organizations/<organization_id>/documents', methods=['POST'])
def upload_organization_documents(organization_id):
    """Upload documents to an organization's bucket."""
    try:
        if 'files' not in request.files:
            return jsonify({"error": "No files provided"}), 400
        
        files = request.files.getlist('files')
        if not files or all(f.filename == '' for f in files):
            return jsonify({"error": "No files selected"}), 400
        
        uploaded_files = []
        
        for file in files:
            if file and file.filename:
                # Validate file type
                if not file.filename.lower().endswith(('.pdf', '.PDF')):
                    return jsonify({"error": f"Only PDF files are allowed. Got: {file.filename}"}), 400
                
                # Read file content
                file_content = file.read()
                
                # Upload to organization bucket
                final_filename = upload_file_to_organization_bucket(file_content, file.filename, organization_id)
                uploaded_files.append(final_filename)
        
        logger.info(f"Successfully uploaded {len(uploaded_files)} files to organization {organization_id}")
        return jsonify({
            "organizationId": organization_id,
            "files": uploaded_files, 
            "message": f"Successfully uploaded {len(uploaded_files)} files"
        })
        
    except Exception as e:
        logger.error(f"File upload error for organization {organization_id}: {str(e)}")
        return jsonify({"error": f"Upload failed: {str(e)}"}), 500

@app.route('/api/organizations/<organization_id>/documents/<document_name>', methods=['DELETE'])
def delete_document(organization_id, document_name):
    """Delete a document from an organization's bucket."""
    try:
        delete_organization_document(organization_id, document_name)
        return jsonify({
            "organizationId": organization_id,
            "document": document_name,
            "message": "Document deleted successfully"
        })
        
    except FileNotFoundError as e:
        return jsonify({"error": str(e)}), 404
    except Exception as e:
        logger.error(f"Error deleting document {document_name} for organization {organization_id}: {str(e)}")
        return jsonify({"error": f"Failed to delete document: {str(e)}"}), 500

# Updated existing endpoints to support organization_id

@app.route('/api/upload', methods=['POST'])
def upload_files():
    """Upload regulation documents to organization's Cloud Storage bucket."""
    try:
        # Get organization ID from request
        organization_id = request.form.get('organizationId') or request.args.get('organizationId')
        if not organization_id:
            return jsonify({"error": "organizationId is required"}), 400
        
        if 'files' not in request.files:
            return jsonify({"error": "No files provided"}), 400
        
        files = request.files.getlist('files')
        if not files or all(f.filename == '' for f in files):
            return jsonify({"error": "No files selected"}), 400
        
        uploaded_files = []
        
        for file in files:
            if file and file.filename:
                # Validate file type
                if not file.filename.lower().endswith(('.pdf', '.PDF')):
                    return jsonify({"error": f"Only PDF files are allowed. Got: {file.filename}"}), 400
                
                # Read file content
                file_content = file.read()
                
                # Upload to organization bucket
                final_filename = upload_file_to_organization_bucket(file_content, file.filename, organization_id)
                uploaded_files.append(final_filename)
        
        logger.info(f"Successfully uploaded {len(uploaded_files)} files to organization {organization_id}")
        return jsonify({
            "organizationId": organization_id,
            "files": uploaded_files, 
            "message": f"Successfully uploaded {len(uploaded_files)} files"
        })
        
    except Exception as e:
        logger.error(f"File upload error: {str(e)}")
        return jsonify({"error": f"Upload failed: {str(e)}"}), 500

@app.route('/api/ai', methods=['POST'])
def start_pipeline():
    """Start analysis pipeline (async) - compatible with Gumloop interface."""
    try:
        data = request.get_json()
        if not data:
            return jsonify({"error": "No JSON data provided"}), 400
        
        action = data.get('action')
        if action != 'startPipeline':
            return jsonify({"error": "Invalid action. Expected 'startPipeline'"}), 400
        
        # Extract required parameters
        original_requirement = data.get('original_requirement')
        regulation_document_name = data.get('regulation_document_name')
        organization_id = data.get('organizationId')
        
        if not original_requirement:
            return jsonify({"error": "original_requirement is required"}), 400
        if not regulation_document_name:
            return jsonify({"error": "regulation_document_name is required"}), 400
        if not organization_id:
            return jsonify({"error": "organizationId is required"}), 400
        
        # Generate job ID
        job_id = str(uuid.uuid4())
        
        # Initialize job
        job_storage[job_id] = {
            'state': 'QUEUED',
            'started_at': datetime.now().isoformat(),
            'organization_id': organization_id
        }
        
        # Start background job
        analysis_params = {
            'original_requirement': original_requirement,
            'regulation_document_name': regulation_document_name,
            'organization_id': organization_id,
            'system_name': data.get('system_name', ''),
            'objective': data.get('objective', ''),
            'req_id': data.get('req_id', ''),
            'temperature': data.get('temperature', 0.1)
        }
        
        thread = threading.Thread(target=run_analysis_job, args=(job_id, analysis_params))
        thread.daemon = True
        thread.start()
        
        return jsonify({
            "runId": job_id,
            "organizationId": organization_id,
            "state": "QUEUED",
            "message": "Analysis pipeline started successfully"
        })
        
    except Exception as e:
        logger.error(f"Pipeline start error: {str(e)}")
        return jsonify({"error": f"Failed to start pipeline: {str(e)}"}), 500

@app.route('/api/ai', methods=['GET'])
def get_pipeline_status():
    """Get pipeline status - compatible with Gumloop interface."""
    try:
        run_id = request.args.get('runId')
        organization_id = request.args.get('organizationId')
        
        if not run_id:
            return jsonify({"error": "runId is required"}), 400
        
        if run_id not in job_storage:
            return jsonify({"error": "Job not found"}), 404
        
        job = job_storage[run_id]
        
        response = {
            "runId": run_id,
            "organizationId": organization_id or job.get('organization_id', 'default'),
            "state": job['state'],
            "started_at": job.get('started_at'),
            "completed_at": job.get('completed_at')
        }
        
        if job['state'] == 'DONE':
            response['result'] = job.get('result')
        elif job['state'] == 'FAILED':
            response['error'] = job.get('error')
        
        return jsonify(response)
        
    except Exception as e:
        logger.error(f"Get pipeline status error: {str(e)}")
        return jsonify({"error": f"Failed to get pipeline status: {str(e)}"}), 500

@app.route('/openapi.yaml', methods=['GET'])
def openapi_spec():
    """Serve OpenAPI specification."""
    try:
        with open('openapi.yaml', 'r') as f:
            return f.read(), 200, {'Content-Type': 'application/x-yaml'}
    except FileNotFoundError:
        return jsonify({"error": "OpenAPI specification not found"}), 404

@app.route('/docs', methods=['GET'])
def swagger_ui():
    """Serve Swagger UI for interactive API documentation."""
    html = """
    <!DOCTYPE html>
    <html>
    <head>
        <title>Requirements Analysis API - Documentation</title>
        <link rel="stylesheet" type="text/css" href="https://unpkg.com/swagger-ui-dist@3.52.5/swagger-ui.css" />
        <style>
            html { box-sizing: border-box; overflow: -moz-scrollbars-vertical; overflow-y: scroll; }
            *, *:before, *:after { box-sizing: inherit; }
            body { margin:0; background: #fafafa; }
        </style>
    </head>
    <body>
        <div id="swagger-ui"></div>
        <script src="https://unpkg.com/swagger-ui-dist@3.52.5/swagger-ui-bundle.js"></script>
        <script src="https://unpkg.com/swagger-ui-dist@3.52.5/swagger-ui-standalone-preset.js"></script>
        <script>
            window.onload = function() {
                const ui = SwaggerUIBundle({
                    url: '/openapi.yaml',
                    dom_id: '#swagger-ui',
                    deepLinking: true,
                    presets: [
                        SwaggerUIBundle.presets.apis,
                        SwaggerUIStandalonePreset
                    ],
                    plugins: [
                        SwaggerUIBundle.plugins.DownloadUrl
                    ],
                    layout: "StandaloneLayout"
                });
            };
        </script>
    </body>
    </html>
    """
    return html, 200, {'Content-Type': 'text/html'}

@app.route('/health', methods=['GET'])
def health_check():
    """Health check endpoint."""
    return jsonify({"status": "healthy", "timestamp": datetime.now().isoformat()})

@app.route('/analyze-requirement', methods=['POST'])
def analyze_requirement():
    """Main endpoint for requirements analysis (synchronous)."""
    try:
        # Parse request data
        data = request.get_json()
        if not data:
            return jsonify({"error": "No JSON data provided"}), 400
            
        # Extract required and optional parameters
        original_requirement = data.get('original_requirement')
        regulation_document_name = data.get('regulation_document_name')
        organization_id = data.get('organizationId')
        
        if not original_requirement:
            return jsonify({"error": "original_requirement is required"}), 400
        if not regulation_document_name:
            return jsonify({"error": "regulation_document_name is required"}), 400
        if not organization_id:
            return jsonify({"error": "organizationId is required"}), 400
            
        # Optional parameters
        system_name = data.get('system_name', '')
        objective = data.get('objective', '')
        req_id = data.get('req_id', '')
        temperature = data.get('temperature', 0.1)
        
        logger.info(f"Starting analysis for requirement: {original_requirement[:50]}...")
        
        # Step 1: Initial Requirements Analysis
        logger.info("Step 1: Analyzing requirement against INCOSE/EARS standards")
        analysis_json = analyze_requirement_step1(
            original_requirement, system_name, objective, req_id, temperature
        )
        
        # Step 2: Regulatory Research
        logger.info("Step 2: Analyzing regulatory compliance")
        try:
            regulation_text = get_regulation_document(regulation_document_name, organization_id)
            analysis_json2 = analyze_regulation_step2(
                analysis_json, regulation_text, regulation_document_name, temperature
            )
        except FileNotFoundError:
            # If no regulation document found, continue with empty regulatory analysis
            logger.warning(f"No regulation document found for organization {organization_id}, continuing without regulatory analysis")
            analysis_json2 = {
                "regulation_document": regulation_document_name,
                "relevant_passages": [],
                "compliance_concerns": ["No regulation document found for analysis"],
                "regulatory_keywords": [],
                "analysis_timestamp": datetime.now().isoformat()
            }
        
        # Step 3: Compliance Integration
        logger.info("Step 3: Integrating compliance findings")
        analysis_json3 = analyze_compliance_step3(
            analysis_json, analysis_json2, temperature
        )
        
        # Prepare final response
        response_data = {
            "status": "success",
            "organizationId": organization_id,
            "analysisJson": analysis_json,
            "analysisJson2": analysis_json2, 
            "analysisJson3": analysis_json3,
            "processed_timestamp": datetime.now().isoformat()
        }
        
        logger.info("Analysis completed successfully")
        return jsonify(response_data)
        
    except json.JSONDecodeError as e:
        logger.error(f"JSON parsing error: {str(e)}")
        return jsonify({"error": f"Invalid JSON in AI response: {str(e)}"}), 500
        
    except Exception as e:
        logger.error(f"Unexpected error: {str(e)}")
        logger.error(traceback.format_exc())
        return jsonify({"error": f"Internal server error: {str(e)}"}), 500

if __name__ == '__main__':
    # Verify required environment variables
    required_env_vars = [
        'GEMINI_API_KEY'
    ]
    
    missing_vars = [var for var in required_env_vars if not os.getenv(var)]
    if missing_vars:
        logger.error(f"Missing required environment variables: {missing_vars}")
        exit(1)
    
    port = int(os.getenv('PORT', 8080))
    app.run(host='0.0.0.0', port=port, debug=False) 
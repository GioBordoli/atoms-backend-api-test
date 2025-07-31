# Requirements Analysis API

A comprehensive FastAPI API for analyzing engineering requirements using INCOSE and EARS standards with regulatory compliance checking. The API integrates with Google Cloud Storage for organization-based document management and uses Google Gemini 2.0 Flash for AI-powered analysis.

## Features

### 🔍 3-Step Analysis Process
1. **INCOSE/EARS Standards Analysis**: Evaluates requirements against industry standards
2. **Regulatory Research**: Searches regulation documents for relevant compliance requirements  
3. **Compliance Integration**: Produces enhanced requirements that meet both standards and regulations

### 🏢 Organization-Based Document Management
- **Isolated Storage**: Each organization gets its own Cloud Storage bucket (`{organizationId}-requirements`)
- **Auto-Creation**: Buckets are automatically created when first document is uploaded
- **Document Versioning**: Automatic filename versioning for duplicates (e.g., `document(1).pdf`)
- **Document Management**: Upload, list, and delete documents per organization

### 🚀 Flexible API Design
- **Synchronous Analysis**: Immediate results via `/analyze-requirement`
- **Asynchronous Pipeline**: Background processing with status polling via `/api/ai`
- **Legacy Compatibility**: Maintains compatibility with existing Gumloop frontend

### 🛠 Technology Stack
- **AI Engine**: Google Gemini 2.0 Flash for intelligent analysis
- **Storage**: Google Cloud Storage with organization-based buckets
- **Authentication**: Service account-based Google Cloud authentication
- **Framework**: Python Flask with comprehensive error handling

## Quick Start

### Prerequisites
- Python 3.8+
- Google Cloud Project with enabled APIs
- Google Cloud Storage access
- Google Gemini API key

### Installation

1. **Clone the repository**
   ```bash
   git clone <repository-url>
   cd requirement-refiner
   ```

2. **Install dependencies**
   ```bash
   pip install -r requirements.txt
   ```

3. **Set up environment variables**
   ```bash
   export GEMINI_API_KEY="your-gemini-api-key"
   export GOOGLE_APPLICATION_CREDENTIALS="/path/to/service-account-key.json"
   ```

4. **Run the application**
   ```bash
   python app.py
   ```

The API will be available at `http://localhost:8080`

## API Endpoints

### Document Management

#### List Organization Documents
```http
GET /api/organizations/{organizationId}/documents
```

#### Upload Documents to Organization
```http
POST /api/organizations/{organizationId}/documents
Content-Type: multipart/form-data

files: [PDF files]
```

#### Delete Organization Document
```http
DELETE /api/organizations/{organizationId}/documents/{documentName}
```

### Requirements Analysis

#### Synchronous Analysis
```http
POST /analyze-requirement
Content-Type: application/json

{
  "original_requirement": "The system shall respond within 2 seconds",
  "regulation_document_name": "fda-regulation.pdf",
  "organizationId": "acme-corp",
  "system_name": "Payment System",
  "objective": "Process transactions securely",
  "req_id": "REQ-001",
  "temperature": 0.1
}
```

#### Asynchronous Analysis
```http
POST /api/ai
Content-Type: application/json

{
  "action": "startPipeline",
  "original_requirement": "The system shall respond within 2 seconds",
  "regulation_document_name": "fda-regulation.pdf",
  "organizationId": "acme-corp"
}
```

Check status:
```http
GET /api/ai?runId={jobId}&organizationId={organizationId}
```

### Legacy Endpoints

#### File Upload (Legacy)
```http
POST /api/upload
Content-Type: multipart/form-data

organizationId: acme-corp
files: [PDF files]
```

## Organization-Based Architecture

### Bucket Structure
Each organization gets its own isolated bucket:
- **Bucket Name**: `{organizationId}-requirements`
- **Auto-Creation**: Created automatically on first upload
- **Location**: US region by default
- **Permissions**: Service account has full access

### Document Versioning
When uploading duplicate filenames:
- `document.pdf` → `document.pdf`
- `document.pdf` (duplicate) → `document(1).pdf`
- `document.pdf` (another duplicate) → `document(2).pdf`

### Security Model
- **Trust-Based**: organizationId parameter is trusted (no verification)
- **Isolation**: Organizations cannot access each other's documents
- **Service Account**: Backend handles all Cloud Storage interactions

## Analysis Process

### Step 1: INCOSE/EARS Analysis
- Evaluates requirement structure and clarity
- Identifies violations of industry standards
- Provides quality rating (1-10 scale)
- Suggests improvements for better compliance

### Step 2: Regulatory Research
- Extracts relevant passages from regulation documents
- Identifies potential compliance concerns
- Assigns relevance scores to regulatory sections
- Extracts key regulatory terms and concepts

### Step 3: Compliance Integration
- Combines standards analysis with regulatory findings
- Resolves conflicts between requirements and regulations
- Produces enhanced requirements meeting all standards
- Provides final quality rating and traceability

## Example Response

```json
{
  "status": "success",
  "organizationId": "acme-corp",
  "analysisJson": {
    "req_id": "REQ-001",
    "original_requirement": "The system shall respond within 2 seconds",
    "incose_format": "The system shall respond to user requests within 2 seconds of receiving the request",
    "ears_format": "When a user request is received, the system shall respond within 2 seconds",
    "quality_rating": "7",
    "feedback": "Good performance criteria but needs specific trigger conditions"
  },
  "analysisJson2": {
    "regulation_document": "fda-regulation.pdf",
    "relevant_passages": [...],
    "compliance_concerns": ["Response time may not meet FDA requirements"]
  },
  "analysisJson3": {
    "final_requirement_ears": "When a critical user request is received, the system shall respond within 1 second to meet FDA compliance",
    "compliance_status": "COMPLIANT",
    "final_quality_rating": "9"
  }
}
```

## Error Handling

The API provides comprehensive error handling:
- **400 Bad Request**: Missing or invalid parameters
- **404 Not Found**: Document or organization not found
- **500 Internal Server Error**: Processing failures

Empty buckets are handled gracefully - analysis continues without regulatory input if no documents are found.

## Interactive Documentation

Visit `/docs` for interactive Swagger UI documentation, or `/openapi.yaml` for the OpenAPI specification.

## Health Check

```http
GET /health
```

Returns service status and timestamp.

## Production Deployment

See [DEPLOYMENT_GUIDE.md](DEPLOYMENT_GUIDE.md) for detailed deployment instructions including:
- Google Cloud Run deployment
- Environment variable configuration
- Service account setup
- Continuous deployment with Cloud Build

## Environment Variables

See [ENVIRONMENT_VARIABLES.md](ENVIRONMENT_VARIABLES.md) for complete environment variable documentation.

## Version History

- **v2.0.0**: Organization-based buckets, document management, removed Google Sheets
# Requirements Analysis API Documentation

## Overview

The Requirements Analysis API provides comprehensive analysis of engineering requirements using EARS and INCOSE standards, with regulatory compliance checking. It replaces the existing Gumloop flow with a Flask-based backend powered by Google Gemini 2.0 Flash.

## Base URL

```
https://YOUR_CLOUD_RUN_URL
```

## Authentication

This API is publicly accessible and does not require authentication.

## Endpoints

### Health Check

**GET** `/health`

Check if the API is running and healthy.

#### Response

```json
{
  "status": "healthy",
  "timestamp": "2024-01-15T10:30:00.000Z"
}
```

### Analyze Requirement

**POST** `/analyze-requirement`

Analyze an engineering requirement against INCOSE and EARS standards, with regulatory compliance checking.

#### Request Body

```json
{
  "original_requirement": "The system shall respond within 2 seconds",
  "regulation_document_name": "ISO-26262.pdf",
  "system_name": "Automotive Control System",
  "objective": "Real-time performance requirements",
  "req_id": "REQ-001",
  "temperature": 0.1
}
```

#### Request Parameters

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `original_requirement` | string | ✅ | - | The original requirement text to analyze |
| `regulation_document_name` | string | ✅ | - | Name of the regulation PDF document in Cloud Storage |
| `system_name` | string | ❌ | "" | Name of the system (optional) |
| `objective` | string | ❌ | "" | Objective or purpose of the requirement (optional) |
| `req_id` | string | ❌ | "" | Requirement ID (will be generated if not provided) |
| `temperature` | number | ❌ | 0.1 | AI model temperature parameter (0.0-1.0) |

#### Response

The API returns a comprehensive analysis in three stages:

```json
{
  "status": "success",
  "analysisJson": {
    "req_id": "REQ-001",
    "original_requirement": "The system shall respond within 2 seconds",
    "incose_format": "The automotive control system shall provide a response to user inputs within a maximum of 2.0 seconds under normal operating conditions.",
    "ears_format": "When the user provides an input, the automotive control system shall respond within 2 seconds.",
    "incose_violations": [
      "Missing trigger condition",
      "Ambiguous 'respond' definition"
    ],
    "ears_violations": [
      "Response definition could be more specific"
    ],
    "requirement_pattern": "performance",
    "quality_rating": "7",
    "feedback": "The requirement addresses performance but needs clarification on response types and trigger conditions.",
    "analysis_timestamp": "2024-01-15T10:30:00.000Z"
  },
  "analysisJson2": {
    "regulation_document": "ISO-26262.pdf",
    "relevant_passages": [
      {
        "section": "Part 6, Section 7.4",
        "text": "Real-time systems shall meet specified timing constraints...",
        "relevance_score": "9",
        "impact": "Defines timing requirements for safety-critical systems"
      }
    ],
    "compliance_concerns": [
      "Need to specify safety integrity level",
      "Missing failure mode analysis"
    ],
    "regulatory_keywords": ["real-time", "timing", "safety-critical", "response time"],
    "analysis_timestamp": "2024-01-15T10:30:00.000Z"
  },
  "analysisJson3": {
    "final_requirement_ears": "When the user provides an input to the automotive control system, the system shall provide a complete response within 2.0 seconds with 99.9% reliability under normal operating conditions, as required by ISO-26262 Part 6 Section 7.4.",
    "final_requirement_incose": "The automotive control system shall provide a complete, valid response to all user inputs within a maximum response time of 2.0 seconds with a reliability of 99.9% under normal operating conditions (temperature: -40°C to +85°C, voltage: 9V to 16V), in compliance with ISO-26262 Part 6 Section 7.4 timing requirements.",
    "compliance_status": "COMPLIANT",
    "identified_conflicts": [],
    "resolution_strategies": [
      "Added reliability requirement for safety compliance",
      "Specified operating conditions",
      "Referenced specific regulatory section"
    ],
    "compliance_recommendations": [
      "Consider adding failure mode behavior",
      "Specify response content requirements",
      "Add monitoring/logging requirements"
    ],
    "regulatory_traceability": [
      "ISO-26262 Part 6 Section 7.4 - Timing Requirements",
      "ISO-26262 Part 4 Section 6.2 - Safety Goals"
    ],
    "final_quality_rating": "9",
    "enhancement_summary": "Enhanced requirement with regulatory compliance, reliability specifications, and operating conditions for safety-critical automotive systems.",
    "analysis_timestamp": "2024-01-15T10:30:00.000Z"
  },
  "processed_timestamp": "2024-01-15T10:30:00.000Z"
}
```

#### Response Fields

##### analysisJson (Step 1: INCOSE/EARS Analysis)
- `req_id`: Extracted or generated requirement ID
- `original_requirement`: The input requirement text
- `incose_format`: Requirement rewritten following INCOSE standards
- `ears_format`: Requirement rewritten in EARS format
- `incose_violations`: List of INCOSE standard violations found
- `ears_violations`: List of EARS format violations found
- `requirement_pattern`: Type of requirement (functional, performance, interface, etc.)
- `quality_rating`: Quality score from 1-10
- `feedback`: Detailed analysis feedback
- `analysis_timestamp`: When the analysis was performed

##### analysisJson2 (Step 2: Regulatory Analysis)
- `regulation_document`: Name of the regulation document analyzed
- `relevant_passages`: Array of relevant regulatory text sections
  - `section`: Regulatory section identifier
  - `text`: Relevant regulatory text
  - `relevance_score`: Relevance rating (1-10)
  - `impact`: Description of regulatory impact
- `compliance_concerns`: List of potential compliance issues
- `regulatory_keywords`: Key regulatory terms identified
- `analysis_timestamp`: When the regulatory analysis was performed

##### analysisJson3 (Step 3: Compliance Integration)
- `final_requirement_ears`: Final requirement in EARS format with compliance
- `final_requirement_incose`: Final requirement in INCOSE format with compliance
- `compliance_status`: COMPLIANT, NON_COMPLIANT, or PARTIAL
- `identified_conflicts`: Conflicts between requirement and regulations
- `resolution_strategies`: Strategies used to resolve conflicts
- `compliance_recommendations`: Recommendations for improvement
- `regulatory_traceability`: List of regulatory sections traced to
- `final_quality_rating`: Final quality score (1-10)
- `enhancement_summary`: Summary of improvements made
- `analysis_timestamp`: When the compliance integration was performed

## Error Responses

### 400 Bad Request

```json
{
  "error": "original_requirement is required"
}
```

### 404 Not Found

```json
{
  "error": "Regulation document not found: ISO-26262.pdf not found in bucket regulations-bucket"
}
```

### 500 Internal Server Error

```json
{
  "error": "Internal server error: Unable to process requirement analysis"
}
```

## Usage Examples

### Basic Analysis

```bash
curl -X POST https://YOUR_CLOUD_RUN_URL/analyze-requirement \
  -H "Content-Type: application/json" \
  -d '{
    "original_requirement": "The system shall authenticate users",
    "regulation_document_name": "NIST-800-63.pdf"
  }'
```

### Complete Analysis with All Parameters

```bash
curl -X POST https://YOUR_CLOUD_RUN_URL/analyze-requirement \
  -H "Content-Type: application/json" \
  -d '{
    "original_requirement": "The system shall process transactions within 5 seconds",
    "regulation_document_name": "PCI-DSS.pdf",
    "system_name": "Payment Processing System",
    "objective": "Ensure fast and secure payment processing",
    "req_id": "REQ-PAY-001",
    "temperature": 0.2
  }'
```

### JavaScript/TypeScript Example

```javascript
const analyzeRequirement = async (requirement, regulationDoc) => {
  const response = await fetch('https://YOUR_CLOUD_RUN_URL/analyze-requirement', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({
      original_requirement: requirement,
      regulation_document_name: regulationDoc,
      system_name: "Web Application",
      temperature: 0.1
    })
  });

  if (!response.ok) {
    throw new Error(`HTTP error! status: ${response.status}`);
  }

  const result = await response.json();
  return result;
};

// Usage
analyzeRequirement(
  "The system shall encrypt all data at rest",
  "GDPR-Guidelines.pdf"
).then(result => {
  console.log('Analysis complete:', result);
}).catch(error => {
  console.error('Analysis failed:', error);
});
```

### Python Example

```python
import requests
import json

def analyze_requirement(requirement, regulation_doc, **kwargs):
    url = "https://YOUR_CLOUD_RUN_URL/analyze-requirement"
    
    payload = {
        "original_requirement": requirement,
        "regulation_document_name": regulation_doc,
        **kwargs
    }
    
    response = requests.post(url, json=payload)
    response.raise_for_status()
    
    return response.json()

# Usage
result = analyze_requirement(
    requirement="The system shall log all user activities",
    regulation_doc="SOX-Compliance.pdf",
    system_name="Financial Reporting System",
    req_id="REQ-LOG-001"
)

print(json.dumps(result, indent=2))
```

## Rate Limits

Currently, there are no explicit rate limits, but Google Cloud Run may apply automatic scaling limits based on:
- Maximum concurrent requests per instance
- CPU and memory usage
- Cold start times

## Data Storage

- Analysis results are automatically stored in the configured Google Sheet
- Original requirements and analysis data are logged for audit purposes
- No personal data is stored permanently (only requirement text and analysis)

## Support and Troubleshooting

### Common Issues

1. **Document not found**: Ensure the regulation document exists in the Cloud Storage bucket
2. **API timeout**: Large documents may take longer to process; consider breaking down complex requirements
3. **Invalid JSON**: Ensure request body is valid JSON format

### Contact

For technical support or API issues, check the deployment logs or refer to the troubleshooting section in the deployment guide. 
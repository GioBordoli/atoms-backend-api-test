# 📧 Frontend Team API Integration Guide

## 🚀 New ATOMS Requirements Analysis API

Hi Frontend Team! 👋

We've successfully deployed the new **ATOMS Requirements Analysis API** to replace the current system. Here's everything you need to integrate seamlessly:

---

## 🔗 API Base URL
```
https://atoms-requirements-api-lyj3ogh7tq-uc.a.run.app
```

## 🔐 Authentication
All endpoints require **Google Cloud Identity Token**:
```javascript
// Get token (users must be in atoms.tech domain)
const token = await gcloud.auth.getIdToken();

// Add to all requests
headers: {
  'Authorization': `Bearer ${token}`,
  'Content-Type': 'application/json'
}
```

---

## 🎯 Primary Endpoint: Requirements Analysis

### **POST** `/analyze-requirement`

**Use this to replace your current requirement processing endpoint.**

### 📤 Request Format:
```javascript
const requestBody = {
  "original_requirement": "The system shall respond within 2 seconds",
  "organizationId": "atoms-tech",                    // Your org ID
  "regulation_document_name": "safety_standards.pdf", // Optional
  "system_name": "User Management System",           // Optional
  "objective": "Performance optimization",           // Optional  
  "req_id": "REQ-001",                              // Optional
  "temperature": 0.1                                // Optional (AI creativity 0.0-1.0)
};
```

### 📥 Response Format:
```javascript
{
  "status": "success",
  "analysisJson": {
    "req_id": "REQ-001",
    "original_requirement": "The system shall respond within 2 seconds",
    "incose_format": "The system shall respond to user requests within 2 seconds.",
    "ears_format": "When a user submits a request, the system shall respond within 2 seconds.",
    "incose_violations": ["List of INCOSE standard violations"],
    "ears_violations": ["List of EARS standard violations"], 
    "requirement_pattern": "Performance",
    "quality_rating": "6",
    "feedback": "Detailed improvement suggestions...",
    "analysis_timestamp": "2025-07-31T00:57:27.679039"
  },
  "analysisJson2": {
    "regulation_document": "safety_standards.pdf",
    "relevant_passages": ["Extracted regulatory text..."],
    "compliance_concerns": ["Identified compliance issues..."],
    "regulatory_keywords": ["safety", "performance"],
    "analysis_timestamp": "2025-07-31T00:57:32.870697"
  },
  "analysisJson3": {
    "final_requirement_ears": "Enhanced EARS format with full context...",
    "final_requirement_incose": "Enhanced INCOSE format with full context...",
    "compliance_status": "COMPLIANT|PARTIAL|NON_COMPLIANT",
    "identified_conflicts": ["Any regulatory conflicts..."],
    "resolution_strategies": ["How to resolve conflicts..."],
    "compliance_recommendations": ["Improvement suggestions..."],
    "regulatory_traceability": ["Links to specific regulations..."],
    "final_quality_rating": "8",
    "enhancement_summary": "What was improved in the final version...",
    "analysis_timestamp": "2025-07-31T00:57:36.889361"
  },
  "processed_timestamp": "2025-07-31T00:57:36.889361"
}
```

---

## ⚡ Alternative: Async Processing

For heavy workloads, use the async pipeline:

### **Start Job:** POST `/api/ai`
```javascript
// Same request body as above
const response = await fetch('/api/ai', {
  method: 'POST',
  headers: authHeaders,
  body: JSON.stringify(requestBody)
});
// Returns: { "runId": "uuid", "state": "QUEUED" }
```

### **Check Status:** GET `/api/ai?runId=${runId}&organizationId=${orgId}`
```javascript
// Returns: { "state": "QUEUED|RUNNING|DONE", "result": {...} }
```

---

## 📁 Document Management

### **List Documents:** GET `/api/organizations/${orgId}/documents`
```javascript
// Returns: { "organizationId": "atoms-tech", "documents": [...], "count": 5 }
```

### **Upload Documents:** POST `/api/organizations/${orgId}/documents`
```javascript
const formData = new FormData();
formData.append('files', file1);
formData.append('files', file2);
// Returns: Upload confirmation
```

### **Delete Document:** DELETE `/api/organizations/${orgId}/documents/${filename}`
```javascript
// Returns: Deletion confirmation
```

---

## 🛠️ Frontend Implementation Example

```javascript
class AtomsAPI {
  constructor() {
    this.baseURL = 'https://atoms-requirements-api-lyj3ogh7tq-uc.a.run.app';
    this.orgId = 'atoms-tech';
  }

  async analyzeRequirement(requirement, options = {}) {
    const token = await this.getAuthToken();
    
    const response = await fetch(`${this.baseURL}/analyze-requirement`, {
      method: 'POST',
      headers: {
        'Authorization': `Bearer ${token}`,
        'Content-Type': 'application/json'
      },
      body: JSON.stringify({
        original_requirement: requirement,
        organizationId: this.orgId,
        ...options
      })
    });

    if (!response.ok) {
      throw new Error(`API Error: ${response.status}`);
    }

    return await response.json();
  }

  async getAuthToken() {
    // Your Google Cloud authentication logic
    return await gcloud.auth.getIdToken();
  }
}

// Usage
const api = new AtomsAPI();
const result = await api.analyzeRequirement(
  "The car should drive at most at 35 mph",
  { system_name: "Vehicle Control System" }
);

console.log('INCOSE Format:', result.analysisJson.incose_format);
console.log('EARS Format:', result.analysisJson.ears_format);
console.log('Quality Rating:', result.analysisJson3.final_quality_rating);
```

---

## 🎯 Key Differences from Old API

1. **Authentication:** Now requires Google Cloud Identity tokens
2. **Response Structure:** Three-step analysis (basic → regulatory → enhanced)
3. **Quality Metrics:** Includes quality ratings and improvement feedback
4. **Async Support:** Can handle long-running analyses
5. **Document Management:** Built-in regulation document handling

---

## 🔧 Health Check
```javascript
GET /health
// Returns: { "status": "healthy", "timestamp": "..." }
```

---

## 📊 Expected Performance
- **Sync Analysis:** ~8-20 seconds (includes AI processing)
- **Async Analysis:** Background processing, check status periodically
- **Document Operations:** ~0.2-0.5 seconds
- **Health Check:** ~0.2 seconds

---

## 🚨 Error Handling
```javascript
// 200: Success
// 401/403: Authentication issues
// 422: Validation errors
// 500: Server errors

// Always check response.ok before processing
if (!response.ok) {
  const error = await response.json();
  console.error('API Error:', error.detail);
}
```

---

## 🎉 Migration Checklist
- [ ] Update base URL to new endpoint
- [ ] Implement Google Cloud Identity token authentication  
- [ ] Update request/response handling for new JSON structure
- [ ] Add error handling for new status codes
- [ ] Test with sample requirements
- [ ] Update any hardcoded timeouts (allow 20+ seconds for analysis)

---

## 📋 Real Example

Here's a real test we ran:

**Input:**
```
"The car should drive at most at 35 mph"
```

**Output:**
- **INCOSE Format:** "The vehicle's maximum speed shall not exceed 35 mph under normal operating conditions. Speed shall be measured using the vehicle's onboard GPS system with an accuracy of ±0.5 mph."
- **EARS Format:** "When the vehicle is operating under normal driving conditions, the vehicle speed, as measured by the vehicle's onboard GPS system with an accuracy of ±0.5 mph, shall not exceed 35 mph."
- **Quality Improvement:** 6 → 8 (33% improvement)

---

## 🆘 Support

**Questions?** The API is fully tested and production-ready. Contact the backend team if you need any clarification!

**API Documentation:** Access the interactive Swagger UI at `/docs` (requires authentication)

Best regards,  
**Backend Team** 🚀 
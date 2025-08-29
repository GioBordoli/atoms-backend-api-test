# ATOMS Requirements Analysis API (v1)

Gumloop-compatible backend with org-scoped storage and prompts-driven analysis. Deployed on Cloud Run.

## URLs
- Swagger: `/docs`
- Redoc: `/redoc`
- OpenAPI: `/openapi.json`
- Versioned alias: `/v1/*` (same routes)

## Quickstart (curl)

- Health
```bash
curl -s https://<SERVICE_URL>/health
```

- Start analysis (text)
```bash
curl -s -X POST https://<SERVICE_URL>/api/ai \
  -H "Content-Type: application/json" \
  -d '{
    "pipelineType": "requirement-analysis",
    "requirement": "The system shall respond within 2 seconds",
    "temperature": 0.1
  }'
```

- Poll status
```bash
curl -s "https://<SERVICE_URL>/api/ai?runId=<RUN_ID>&organizationId=atoms-tech"
```

- Create requirement (sync + persist)
```bash
curl -s -X POST https://<SERVICE_URL>/api/requirements \
  -H "Content-Type: application/json" \
  -d '{
    "organizationId": "atoms-tech",
    "original_requirement": "The system shall respond within 2 seconds",
    "systemName": "Web App",
    "objective": "Performance"
  }'
```

- List requirements
```bash
curl -s "https://<SERVICE_URL>/api/requirements?organizationId=atoms-tech&page=1&pageSize=10"
```

## FE integration
- Keep existing Next.js routes and proxy to the backend with `ATOMS_API_URL`.
- Returned shapes match Gumloop:
  - `POST /api/ai` → `{ run_id }`
  - `GET /api/ai` → `{ run_id, state, outputs: { analysisJson[], analysisJson2[], analysisJson3[] }, credit_cost }`
- Prompts are plain text in `prompts/`.

## OpenAPI and SDK
- Download OpenAPI: `https://<SERVICE_URL>/openapi.json`
- Generate types: `npx openapi-typescript https://<SERVICE_URL>/openapi.json -o sdk/types.ts`
- Mock server: `prism mock openapi.yaml`

## Versioning
- All routes available under `/v1/*`.

## Deploy
- Artifact Registry + Cloud Run; secrets via Secret Manager (`GEMINI_API_KEY`, `ALLOWED_ORIGINS`). 
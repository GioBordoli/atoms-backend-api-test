# Vertex AI ADK Agent (requirement-analysis) with Supabase Save

## Scope and Success Criteria
- Single `pipelineType`: `requirement-analysis`.
- Fixed model/temperature (env-defaults):
  - `MODEL_NAME=gemini-2.5-pro`
  - `TEMPERATURE=0.2`
- Inputs: `requirement`, `file_urls[]` (public/presigned), `systemName`, `objective`.
- Outputs: `analysisJson`, `analysisJson2`, `analysisJson3` as arrays of stringified JSON with exact UI keys; `credit_cost=0`; `run_id` lifecycle via Agent Engine sessions.
- Supabase save: insert into `public.requirements` per agreed mapping; generate `external_id` (REQ-00001); return row id + external_id.

## Milestone 1: Agent Core (Local)
- Implement `refine_requirement`:
  - Use prompts in `prompts/step1.txt`, `prompts/step2.txt` (stub no-reg), `prompts/step3.txt`.
  - Model: `gemini-2.5-pro`; temperature from env (default 0.2).
  - Build legacy-compatible outputs:
    - `analysisJson`: keys `Original Requirement`, `EARS Generated Requirement`, `EARS Pattern`, `EARS_SYNTAX_TEMPLATE`, `INCOSE_FORMAT`, `INCOSE_REQUIREMENT_FEEDBACK`.
    - `analysisJson2`: keys `RELEVANT_REGULATIONS`, `COMPLIANCE_FEEDBACK`.
    - `analysisJson3`: keys `ENHANCED_REQUIREMENT_EARS`, `ENHANCED_REQUIREMENT_INCOSE`, `ENHANCED_GENERAL_FEEDBACK`.
- Implement `fetch_file_urls(file_urls)`:
  - Validate: ≤10 files; types: pdf/md; size ≤25MB; HTTPS only.
  - Fetch, parse: PDF via PyPDF2; MD as text; concatenate; truncate if needed.
  - On violations: 400 `VALIDATION_ERROR`; structured error JSON.
- Error builder:
  - 400 `VALIDATION_ERROR`, 404 `NOT_FOUND`, 429 `RATE_LIMITED`, 502/503 `MODEL_ERROR`, 500 `INTERNAL_ERROR`.
- Logging/tracing:
  - Log start, file fetches (name/size/type), errors, finish, timings; enable Vertex trace context.
- Local verification: run refine with a sample requirement and confirm outputs keys/shape.

## Milestone 2: Supabase Save Tool (Local)
- Implement `save_requirement_supabase`:
  - Inputs from FE: `document_id`, `block_id`, `name`, optional `created_by`, `tags`, `original_requirement`.
  - Generate `external_id` (REQ-00001) and return with inserted row id.
  - Insert mapping:
    - `enchanced_requirement`: final INCOSE.
    - `ai_analysis`: parsed analysisJson/2/3 + finals (`final_requirement_ears`, `final_requirement_incose`, `compliance_status`, `final_quality_rating`, `regulatory_traceability`).
    - `properties`: `{ final_requirement_ears, final_requirement_incose, compliance_status, final_quality_rating }`.
  - Defaults: `status=active`, `format=incose`; `priority`/`level` DB defaults.
- Config: `SUPABASE_URL`, `SUPABASE_SERVICE_KEY`, `SUPABASE_TABLE=public.requirements`.
- Local test: insert sample row; confirm constraints (name length, FK present).

## Milestone 3: Agent Engine Deploy (us-central1)
- Service account:
  - Create SA (e.g., `adk-agent-sa@PROJECT.iam.gserviceaccount.com`).
  - Roles (least privilege): `Vertex AI User` (or Agent Engine-specific), `Logging Writer`; add `Secret Manager Access` if used.
- Deploy ADK agent to Agent Engine in `us-central1`; capture `GOOGLE_CLOUD_AGENT_ENGINE_ID`.
- Sessions/polling:
  - Start: Reasoning Engine `:query` → return `run_id` immediately.
  - Poll: sessions API → `RUNNING`/`DONE`/`FAILED`; `DONE` returns outputs; `credit_cost=0`.

## Milestone 4: API and Ops Hand-off
- REST docs:
  - Start (query): `POST https://{LOCATION}-aiplatform.googleapis.com/v1beta1/projects/{PROJECT}/locations/{LOCATION}/reasoningEngines/{AGENT_ENGINE_ID}:query`
  - Poll (sessions): `GET .../reasoningEngines/{AGENT_ENGINE_ID}/sessions/{run_id}`
- Env/config:
  - `GOOGLE_CLOUD_PROJECT`, `GOOGLE_CLOUD_LOCATION=us-central1`, `GOOGLE_CLOUD_AGENT_ENGINE_ID`, `MODEL_NAME`, `TEMPERATURE`; `SUPABASE_URL`, `SUPABASE_SERVICE_KEY`.
- Logs/trace:
  - Cloud Logging filters; trace guidance.
- Postman collection (optional): start/poll examples.
- Golden sample: one sanitized run with inputs/outputs.

## Milestone 5: FE Cutover and E2E Test
- FE points Next.js `/api/ai` to Agent Engine (server-side SA auth).
- Verify start (<3s run_id), poll → DONE; outputs parity; error envelopes; logs show start/fetch/errors/finish with durations.

## Timeline
- Day 1–2: Core agent, prompts, file tool, errors, logging; local verification.
- Day 3–4: Agent Engine deploy, sessions mapping; outputs parity; Supabase save wired.
- Day 5: Docs (REST, envs), logs/trace guide, Postman; golden run.
- Day 6: FE wiring and joint E2E test.

## Open Items
- `external_id` scope: global sequence (default REQ-00001) or scoped per document/org?
- Text truncation policy for extremely large concatenated file contents.
- Unknown `pipelineType`: respond with 400 `VALIDATION_ERROR` (default) or default to `requirement-analysis`. 
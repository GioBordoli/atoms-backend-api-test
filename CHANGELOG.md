# Changelog

## v1.0.0
- Introduced wrapper app with `/v1` alias and OpenAPI servers metadata.
- Kept UI-compatible `/api/ai` start/poll shapes.
- Added org-scoped requirements persistence and sync creation endpoints.
- Prompts externalized to `prompts/`.
- CORS via `ALLOWED_ORIGINS` secret; secrets via Secret Manager. 
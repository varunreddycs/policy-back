# Frontend Summary

Date: 2026-03-04
Location: apps/web

## Stack
- React + Vite + TypeScript + MUI
- Routes: /console, /audit

## Key Features
- Premium dark enterprise theme via reusable branding pattern:
  - src/theme/defaultBranding.js
  - src/theme/useBranding.js
  - src/theme/buildTheme.js
- Console flow:
  - Ask form + quick-reply chips
  - Answer stream (last 10)
  - Citations chips (copy)
  - Confidence/mode/department/refusal chips
  - Evidence drawer with expandable evidence table
- Audit flow:
  - Load by audit ID (query param supported)
  - Replay audit
  - Pretty JSON panels

## Runtime Config
- VITE_API_BASE_URL
- VITE_TENANT_ID
- VITE_DEFAULT_EMAIL
- VITE_DEFAULT_ROLE
- VITE_DEFAULT_DEPARTMENT
- Template file: apps/web/.env.example

## Docker Integration
- Frontend is built during Docker image build (Node stage)
- Built files are copied into apps/web/dist inside the API image
- FastAPI serves SPA and assets from the same container on port 8000

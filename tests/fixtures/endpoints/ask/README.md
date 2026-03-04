# Ask endpoint fixtures

Endpoint:
- `POST /v1/ask`

Fixtures in this folder are allowed to use a more UI-friendly camelCase shape.

The integration test normalizes these keys to the API schema:
- `tenantId` -> `tenant_id`
  - Special-case: `"local"` -> `DEFAULT_TENANT_ID` (env var)
- `policyScope` -> `scope`
  - `onlyCurrent` -> `only_current`
  - `policyTypes` -> `policy_types`
- If `user` is present and has no `tenant_id`, the test fills it from the request tenant.

If you want a raw API-schema fixture (no normalization), use snake_case keys directly.

## Fixtures
- `request.json`: baseline **API schema** (snake_case + UUIDs).
- `request_automation.json`: baseline **automation schema** (camelCase + `tenantId: "local"`).
- `request_conflicted_user.json`: conflicted user **API schema** (snake_case + UUIDs).
- `request_conflicted_user_automation.json`: conflicted user **automation schema** (camelCase + `tenantId: "local"`).
- `request_api_schema.json`: extra API-schema example (kept for reference).

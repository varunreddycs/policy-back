# Swagger Test Questions

Structured test question payloads for the `/v1/ask` endpoint.
Copy-paste any JSON file into Swagger UI (`http://localhost:8000/docs`) to test.

## Directory Structure

```
swagger_questions/
  _templates/              # Base request templates (copy & customize)
    strict.json            # Strict mode template
    relaxed.json           # Relaxed mode template
    scoped.json            # Template with policy_types scope filter
  ohio/                    # Ohio corpus (171 policies)
    leave_and_benefits/    # Leave, PTO, FMLA, benefits questions
    claims/                # Claims processing, appeals, adjudication
    compliance_and_ethics/ # Ethics, conflicts of interest, regulatory
    operations/            # Operational procedures, workflows
    general/               # Cross-cutting / general policy questions
  cross_policy/            # Questions that span multiple policy domains
```

## Adding a New Jurisdiction or Policy Set

1. Create a folder: `swagger_questions/<jurisdiction>/`
2. Add sub-folders per policy domain (mirror the categories above or create new ones)
3. Each JSON file = one question payload, ready to paste into Swagger

## Naming Convention

```
<topic>__<variant>.json
```

Examples:
- `fmla_eligibility__strict.json`
- `fmla_eligibility__relaxed.json`
- `appeals_deadline__scoped_claims.json`

The double-underscore separates the **topic** from the **variant** (mode, scope, role, etc.).

## JSON Format

All files use the **API schema** (snake_case). Paste directly into Swagger `POST /v1/ask`.

```json
{
  "tenant_id": "00000000-0000-0000-0000-000000000001",
  "question": "Your question here",
  "mode": "strict",
  "user": {
    "tenant_id": "00000000-0000-0000-0000-000000000001",
    "email": "test@test.com",
    "role": "staff",
    "department": "operations"
  },
  "scope": {
    "only_current": true
  }
}
```

### Key Fields

| Field | Values | Notes |
|-------|--------|-------|
| `mode` | `"strict"`, `"relaxed"` | Strict = higher confidence threshold |
| `scope.only_current` | `true`, `false` | Filter to current policy versions only |
| `scope.policy_types` | `["general"]`, `["claims"]`, etc. | Optional filter by policy type |
| `user.role` | `"staff"`, `"admin"`, `"user"` | Affects retrieval context |
| `user.department` | `"operations"`, `"claims_ops"`, `"compliance"`, etc. | Affects department-scoped retrieval |

## What to Look For in Responses

- `audit_id` — every request gets an audit trail UUID
- `retrieval_log.fts_candidates` — full-text search hits (should be > 0 for good questions)
- `retrieval_log.vector_candidates` — embedding search hits (0 if no embeddings deployment configured)
- `citation_items` — matched policy sections with citations
- `evidence` — evidence objects backing the answer
- `decision.selected_bucket` — confidence bucket: `"high"`, `"medium"`, `"low"`, `"none"`

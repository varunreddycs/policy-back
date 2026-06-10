# Azure Developer CLI Deployment Runbook (azd)

This runbook reflects the real deployment issues we hit and the exact sequence that works reliably for this repo.

## What Gets Deployed

- `web` -> Azure Static Web Apps (`apps/web`)
- `api` -> Azure Container Apps (public ingress)
- `worker` -> Azure Container Apps (no ingress)
- Azure Container Registry (ACR)
- Azure Database for PostgreSQL Flexible Server
- Azure Storage (Blob + Queue)
- Azure Key Vault

## Prerequisites

- Azure subscription with Contributor-level permissions on target resource group
- `azd` installed and authenticated
- `az` installed and authenticated
- Docker Desktop installed and running
- Node.js 20+
- From repo root: `policy-back`

## 1) Preflight Checks

Run these before any deploy command:

```powershell
az account show --query "{sub:id,name:name,tenant:tenantId}" -o table
azd version
docker version --format '{{.Server.Version}}'
```

If Docker is not running, start Docker Desktop first. `azd provision` fails fast when Docker daemon is unavailable.

## 2) Login and Environment Setup

```powershell
az login --use-device-code
azd auth login
azd env new dev
azd env select dev
```

Set core environment values:

```powershell
azd env set AZURE_SUBSCRIPTION_ID <subscription-id>
azd env set AZURE_LOCATION eastus2
azd env set AZURE_RESOURCE_GROUP <resource-group>
azd env set resourceGroupName <resource-group>
azd env set environmentName dev
azd env set appEnvironment dev
azd env set apiImageTag dev
azd env set workerImageTag dev
```

## 3) Set Required Parameters (Important)

Use `azd env set` for values consumed by Bicep parameters.

```powershell
azd env set postgresAdminPassword <strong-password>
azd env set azureOpenAiApiKey <openai-api-key>
azd env set azureOpenAiEndpoint https://<resource>.openai.azure.com
azd env set azureOpenAiEmbeddingsDeployment <embedding-deployment>
azd env set azureOpenAiApiVersion 2024-02-15-preview
```

For `postgresAdminPassword`, prefer strong alphanumeric values. This avoids shell escaping issues in non-interactive runs.

## 4) Cheap SKU Profile

If you want a low-cost dev profile:

```powershell
azd env set acrSku Basic
azd env set staticWebAppSku Free
azd env set postgresSkuName Standard_B1ms
azd env set postgresSkuTier Burstable
azd env set postgresStorageSizeGb 32
azd env set apiMinReplicas 1
azd env set apiMaxReplicas 1
azd env set workerMinReplicas 1
azd env set workerMaxReplicas 1
```

## 5) Provision Infrastructure

```powershell
azd provision --no-prompt
```

If this succeeds, continue to Step 7.

## 6) Provision Error Recovery (Known Issues)

### A) `DeploymentActive` for `postgresDeploy`

Symptom:
- `Validation Error Details: DeploymentActive ... deployments/postgresDeploy is still active`

Fix:

```powershell
az deployment group cancel --resource-group <resource-group> --name postgresDeploy
azd provision --no-prompt
```

### B) Container App image pull failure on first run

Symptom:
- `unable to pull image ... policy-api:<tag>` or `policy-worker:<tag>`

Fix:
1. Get ACR name/login server from env or portal.
2. Build and push the expected tags.
3. Re-run provision.

```powershell
az acr login --name <acr-name>
docker build -f apps/api/Dockerfile -t <acr-login-server>/policy-api:dev .
docker push <acr-login-server>/policy-api:dev
docker build -f apps/worker/Dockerfile -t <acr-login-server>/policy-worker:dev .
docker push <acr-login-server>/policy-worker:dev
azd provision --no-prompt
```

## 7) Deploy Application Services

Recommended order for this repo:

```powershell
azd deploy web --no-prompt
```

Why web-only deploy here:
- We observed intermittent `azd deploy` patch failures on Container Apps (`ContainerAppSecretRefNotFound`) even when secrets existed and apps were healthy.
- Infra provisioning already creates API and worker revisions.

If you still want full deploy attempt:

```powershell
azd deploy --no-prompt
```

If it fails with `ContainerAppSecretRefNotFound`, use web-only deploy and validate API/worker health directly (Step 8).

## 8) Verify Runtime Health

Get outputs:

```powershell
azd env get-values
```

Validate endpoints:

```powershell
./scripts/healthcheck.ps1 -ApiBaseUrl <API_URL>
Invoke-WebRequest -Uri <WEB_URL> -UseBasicParsing
```

Inspect Container Apps if API is unhealthy:

```powershell
az containerapp revision list --name policy-api-dev --resource-group <resource-group> -o table
az containerapp logs show --name policy-api-dev --resource-group <resource-group> --type system --tail 100
```

## 9) Key Vault RBAC Propagation Delay

Symptom:
- API/worker revision unhealthy with Key Vault `403 ForbiddenByRbac` while fetching secret refs.

This is usually eventual consistency for RBAC role assignment propagation.

Fix:
1. Wait a few minutes.
2. Trigger a new revision.

```powershell
$ts=(Get-Date -Format yyyyMMddHHmmss)
az containerapp update --name policy-api-dev --resource-group <resource-group> --set-env-vars RBAC_REFRESH=$ts
az containerapp update --name policy-worker-dev --resource-group <resource-group> --set-env-vars RBAC_REFRESH=$ts
```

## 10) Outputs You Should Capture

- `API_URL`
- `WEB_URL`
- `AZURE_CONTAINER_REGISTRY_NAME`
- `STORAGE_ACCOUNT_NAME`
- `POSTGRES_HOST`
- `KEY_VAULT_NAME`

## 11) PostgreSQL pgvector

Ensure extensions exist (if not already created by migrations):

```sql
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pgcrypto;
```

## 12) Custom Domains (Manual)

```powershell
./scripts/postdeploy_print_domains.ps1
```

Use portal-provided DNS verification records exactly.

## 13) Destroy Environment

```powershell
azd down
```

Use with care in shared subscriptions.

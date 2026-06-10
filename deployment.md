# PolicyPlatform — Deployment Guide

## Architecture

| Layer | Azure Service | Notes |
|-------|--------------|-------|
| API | Container App `policy-api-dev` | FastAPI, port 8000 |
| Worker | Container App `policy-worker-dev` | Queue consumer |
| Frontend | Static Web App | Vite/React, auto-built by azd |
| Database | **Cosmos DB NoSQL** (`platformpolicycosmos`) | External — provisioned separately |
| Storage | Azure Storage Account (`stcspdvt2r2ufxa`) | Blobs + Queue |
| Registry | ACR (`acrcspdvt2r2ufxa.azurecr.io`) | Images pushed on deploy |
| Secrets | Key Vault (`kv-cspdvt2r2ufxa`) | cosmos-key, openai-key, storage conn string |

PostgreSQL has been removed. `DB_BACKEND=cosmos` is hardcoded in the Bicep infra.

---

## Prerequisites

```powershell
winget upgrade Microsoft.Azd          # azd >= 1.25 (currently on 1.23.7)
winget install Microsoft.AzureCLI     # az CLI
# Docker Desktop must be running

az login --use-device-code
azd auth login
```

---

## First-Time Setup

### 1 — OIDC service principal (run once)

```powershell
azd pipeline config --provider github
```

This creates the Entra ID app registration, federated credential, and automatically pushes
`AZURE_CLIENT_ID`, `AZURE_TENANT_ID`, `AZURE_SUBSCRIPTION_ID` to GitHub secrets.

If blocked by MFA, create manually:

```powershell
$app = az ad app create --display-name "policy-platform-cicd" | ConvertFrom-Json
$sp  = az ad sp create --id $app.appId | ConvertFrom-Json

az role assignment create `
  --assignee $sp.appId `
  --role Contributor `
  --scope "/subscriptions/c8ab0bbd-99e6-449b-8146-069d433c6e1a/resourceGroups/my-personal"

az ad app federated-credential create --id $app.id --parameters '{
  "name": "github-actions",
  "issuer": "https://token.actions.githubusercontent.com",
  "subject": "repo:varunreddycs/policy-back:ref:refs/heads/main",
  "audiences": ["api://AzureADTokenExchange"]
}'

# Then set AZURE_CLIENT_ID GitHub secret to $app.appId
```

### 2 — GitHub Secrets

```powershell
gh secret set AZURE_CLIENT_ID      # from step 1
gh secret set AZURE_TENANT_ID      --body "b15acec7-ed1f-479b-96d2-7643146dc11c"
gh secret set AZURE_SUBSCRIPTION_ID --body "c8ab0bbd-99e6-449b-8146-069d433c6e1a"
gh secret set AZURE_OPENAI_API_KEY
gh secret set COSMOS_KEY
```

### 3 — GitHub Variables

```powershell
gh variable set AZURE_RESOURCE_GROUP              --body "my-personal"
gh variable set AZURE_OPENAI_ENDPOINT             --body "https://mythri-resource.openai.azure.com"
gh variable set AZURE_OPENAI_EMBEDDINGS_DEPLOYMENT --body "text-embedding-3-large"
gh variable set AZURE_OPENAI_API_VERSION          --body "2024-02-15-preview"
gh variable set COSMOS_ENDPOINT                   --body "https://platformpolicycosmos.documents.azure.com:443/"
gh variable set COSMOS_DATABASE                   --body "policydb"
```

### 4 — azd env (local/manual deploy)

```powershell
azd env select dev
azd env set AZURE_RESOURCE_GROUP my-personal
azd env set cosmosEndpoint "https://platformpolicycosmos.documents.azure.com:443/"
azd env set cosmosDatabase "policydb"
azd env secret set cosmosKey "<cosmos-primary-key>"
azd env secret set azureOpenAiApiKey "<openai-api-key>"
azd env set azureOpenAiEndpoint "https://mythri-resource.openai.azure.com"
azd env set azureOpenAiEmbeddingsDeployment "text-embedding-3-large"
azd env set azureOpenAiApiVersion "2024-02-15-preview"

azd up --no-prompt
```

---

## CI/CD (ongoing)

Push to `main` → GitHub Actions runs `azd up` automatically via `.github/workflows/azure-dev.yml`.

Redeploy without infra changes:

```powershell
azd deploy api worker web --no-prompt
```

---

## Validate After Deploy

```powershell
$api = (azd env get-values | Select-String 'API_URL="([^"]+)"').Matches.Groups[1].Value

Invoke-RestMethod "$api/health"

Invoke-RestMethod "$api/ask" -Method Post -ContentType "application/json" -Body '{
  "query": "What is the acceptable use policy?",
  "tenant_id": "00000000-0000-0000-0000-000000000001",
  "top_k": 3
}'
```

---

## Rollback

```powershell
# List available image tags in ACR
az acr repository show-tags --name acrcspdvt2r2ufxa --repository policy-api --orderby time_desc

azd env set apiImageTag "<sha-to-rollback-to>"
azd env set workerImageTag "<sha-to-rollback-to>"
azd deploy api worker --no-prompt
```

---

## Rotate a Secret

```powershell
az keyvault secret set --vault-name kv-cspdvt2r2ufxa --name cosmos-key --value "<new-key>"

# Force Container Apps to reload the new secret
$ts = Get-Date -Format yyyyMMddHHmmss
az containerapp update --name policy-api-dev    --resource-group my-personal --set-env-vars SECRET_REFRESH=$ts
az containerapp update --name policy-worker-dev --resource-group my-personal --set-env-vars SECRET_REFRESH=$ts
```

---

## Troubleshooting

**Container image pull failure on first provision**

```powershell
az acr login --name acrcspdvt2r2ufxa
docker build -f apps/api/Dockerfile    -t acrcspdvt2r2ufxa.azurecr.io/policy-api:dev .
docker push acrcspdvt2r2ufxa.azurecr.io/policy-api:dev
docker build -f apps/worker/Dockerfile -t acrcspdvt2r2ufxa.azurecr.io/policy-worker:dev .
docker push acrcspdvt2r2ufxa.azurecr.io/policy-worker:dev
azd provision --no-prompt
```

**Key Vault RBAC propagation delay (`ForbiddenByRbac` in logs)**

Wait 2 minutes then restart containers:

```powershell
$ts = Get-Date -Format yyyyMMddHHmmss
az containerapp update --name policy-api-dev    --resource-group my-personal --set-env-vars RBAC_REFRESH=$ts
az containerapp update --name policy-worker-dev --resource-group my-personal --set-env-vars RBAC_REFRESH=$ts
```

**Cosmos DB 401 Unauthorized**

Verify the `cosmos-key` secret in Key Vault matches the current primary key shown in the Azure Portal under the Cosmos DB account → Keys.

**`DeploymentActive` error during provision**

```powershell
az deployment group cancel --resource-group my-personal --name containerAppsDeploy
azd provision --no-prompt
```

**View live container logs**

```powershell
az containerapp logs show --name policy-api-dev --resource-group my-personal --follow
```

---

## Key Resources

| | |
|---|---|
| Resource Group | `my-personal` |
| API URL | `https://policy-api-dev.purpleglacier-f66f3ddd.eastus2.azurecontainerapps.io` |
| Web URL | `https://ambitious-moss-03cc3bd0f.1.azurestaticapps.net` |
| Previous domain | `https://platform.mistrv.com` (re-map to Static Web App custom domain if needed) |
| ACR | `acrcspdvt2r2ufxa.azurecr.io` |
| Key Vault | `kv-cspdvt2r2ufxa` |
| Cosmos DB | `platformpolicycosmos.documents.azure.com` |
| GitHub repo | `https://github.com/varunreddycs/policy-back` |

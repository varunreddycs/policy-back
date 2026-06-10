# Deployment (azd) - Corrected Runbook

This file mirrors `README_DEPLOY_AZD.md` and is the canonical quick reference for reliable deployment.

For full details and troubleshooting, use:
- `README_DEPLOY_AZD.md`

## Quick Path (Reliable)

1. Preflight

```powershell
az account show --query "{sub:id,name:name,tenant:tenantId}" -o table
azd version
docker version --format '{{.Server.Version}}'
```

2. Login and env

```powershell
az login --use-device-code
azd auth login
azd env new dev
azd env select dev
```

3. Set required values

```powershell
azd env set AZURE_SUBSCRIPTION_ID <subscription-id>
azd env set AZURE_LOCATION eastus2
azd env set AZURE_RESOURCE_GROUP <resource-group>
azd env set resourceGroupName <resource-group>
azd env set environmentName dev
azd env set appEnvironment dev
azd env set apiImageTag dev
azd env set workerImageTag dev
azd env set postgresAdminPassword <strong-alphanumeric-password>
azd env set azureOpenAiApiKey <openai-api-key>
azd env set azureOpenAiEndpoint https://<resource>.openai.azure.com
azd env set azureOpenAiEmbeddingsDeployment <embedding-deployment>
azd env set azureOpenAiApiVersion 2024-02-15-preview
```

4. Cheap SKU profile (optional)

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

5. Provision

```powershell
azd provision --no-prompt
```

6. Deploy web

```powershell
azd deploy web --no-prompt
```

7. Validate

```powershell
azd env get-values
./scripts/healthcheck.ps1 -ApiBaseUrl <API_URL>
Invoke-WebRequest -Uri <WEB_URL> -UseBasicParsing
```

## Common Failure Fixes

- `DeploymentActive` on `postgresDeploy`:

```powershell
az deployment group cancel --resource-group <resource-group> --name postgresDeploy
azd provision --no-prompt
```

- Container image pull failure on first provision:

```powershell
az acr login --name <acr-name>
docker build -f apps/api/Dockerfile -t <acr-login-server>/policy-api:dev .
docker push <acr-login-server>/policy-api:dev
docker build -f apps/worker/Dockerfile -t <acr-login-server>/policy-worker:dev .
docker push <acr-login-server>/policy-worker:dev
azd provision --no-prompt
```

- Key Vault RBAC propagation delay (`ForbiddenByRbac` in Container Apps logs):

```powershell
$ts=(Get-Date -Format yyyyMMddHHmmss)
az containerapp update --name policy-api-dev --resource-group <resource-group> --set-env-vars RBAC_REFRESH=$ts
az containerapp update --name policy-worker-dev --resource-group <resource-group> --set-env-vars RBAC_REFRESH=$ts
```

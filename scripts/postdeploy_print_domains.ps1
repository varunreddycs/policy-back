param(
    [string]$ApiHostname = "api.mistrv.com",
    [string]$WebHostname = "platform.mistrv.com"
)

Write-Host "[Post-Deploy Domain Steps]" -ForegroundColor Cyan

if (-not $env:API_URL) {
    Write-Warning "API_URL not found in environment. Run 'azd env get-values' after deploy."
} else {
    Write-Host "API URL: $($env:API_URL)"
}

if (-not $env:WEB_URL) {
    Write-Warning "WEB_URL not found in environment. Run 'azd env get-values' after deploy."
} else {
    Write-Host "Web URL: $($env:WEB_URL)"
}

Write-Host ""
Write-Host "Container Apps custom domain (api):" -ForegroundColor Yellow
Write-Host "1. Open Azure Portal -> Container Apps -> API app -> Custom domains"
Write-Host "2. Add hostname: $ApiHostname"
Write-Host "3. Create DNS record from your DNS provider as prompted (TXT/CNAME)."
Write-Host "4. Create managed certificate and bind it to the hostname."

Write-Host ""
Write-Host "Static Web Apps custom domain (platform):" -ForegroundColor Yellow
Write-Host "1. Open Azure Portal -> Static Web App -> Custom domains"
Write-Host "2. Add hostname: $WebHostname"
Write-Host "3. Create DNS validation record (TXT/CNAME) in your DNS provider."
Write-Host "4. Validate and complete binding in Azure portal."

Write-Host ""
Write-Host "DNS quick guidance:" -ForegroundColor Yellow
Write-Host "- api.mistrv.com: usually CNAME to the Container Apps generated FQDN."
Write-Host "- platform.mistrv.com: usually CNAME to the Static Web App default hostname."
Write-Host "- Always use portal-provided exact records for final setup."

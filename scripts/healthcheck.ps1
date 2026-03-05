param(
    [string]$ApiBaseUrl = $env:API_URL
)

if (-not $ApiBaseUrl) {
    throw "ApiBaseUrl is empty. Provide -ApiBaseUrl or set API_URL in your shell."
}

$healthUrl = "$($ApiBaseUrl.TrimEnd('/'))/health"
$docsUrl = "$($ApiBaseUrl.TrimEnd('/'))/docs"

Write-Host "Checking API endpoints for $ApiBaseUrl" -ForegroundColor Cyan

try {
    $health = Invoke-RestMethod -Method Get -Uri $healthUrl -TimeoutSec 30
    Write-Host "[OK] /health response:" -ForegroundColor Green
    $health | ConvertTo-Json -Depth 8
}
catch {
    Write-Error "Health check failed: $($_.Exception.Message)"
    exit 1
}

try {
    $docs = Invoke-WebRequest -Method Get -Uri $docsUrl -TimeoutSec 30
    if ($docs.StatusCode -ge 200 -and $docs.StatusCode -lt 400) {
        Write-Host "[OK] /docs HTTP $($docs.StatusCode)" -ForegroundColor Green
    } else {
        Write-Error "Docs endpoint returned HTTP $($docs.StatusCode)"
        exit 1
    }
}
catch {
    Write-Error "Docs check failed: $($_.Exception.Message)"
    exit 1
}

Write-Host "Health checks passed." -ForegroundColor Green

# PolicyDocs demo runner (edit BASE_URL if needed)
$BASE_URL = "http://localhost:8000"
$Headers = @{ "Content-Type" = "application/json" }

function Invoke-RestMethodVerboseError {
  param(
    [Parameter(Mandatory=$true)][string]$Method,
    [Parameter(Mandatory=$true)][string]$Uri,
    [Parameter(Mandatory=$false)][hashtable]$Headers,
    [Parameter(Mandatory=$false)][string]$Body
  )

  try {
    if ($null -ne $Body) {
      return Invoke-RestMethod -Method $Method -Uri $Uri -Headers $Headers -Body $Body
    }
    return Invoke-RestMethod -Method $Method -Uri $Uri -Headers $Headers
  }
  catch {
    Write-Host "--- HTTP request failed ---" -ForegroundColor Red
    Write-Host ("{0} {1}" -f $Method, $Uri)
    Write-Host $_.Exception.Message

    if ($_.Exception.Response) {
      try {
        $resp = $_.Exception.Response
        Write-Host ("HTTP {0} {1}" -f [int]$resp.StatusCode, $resp.StatusDescription)
        $sr = New-Object System.IO.StreamReader($resp.GetResponseStream())
        $respBody = $sr.ReadToEnd()
        $sr.Close()
        if ($respBody) {
          Write-Host "--- response body ---"
          Write-Host $respBody
        }
      } catch {
        # ignore
      }
    }

    throw
  }
}

$payloads = Get-Content -Raw -Path (Join-Path $PSScriptRoot "example_api_payloads.json") | ConvertFrom-Json
$tenantId = $payloads.tenant_id
$runStamp = Get-Date -Format "yyyyMMdd-HHmmss"

Write-Host "1) Create ingest batch"
$batchBody = ($payloads.create_batch | ConvertTo-Json -Depth 10)
$batch = Invoke-RestMethodVerboseError -Method Post -Uri "$BASE_URL/v1/ingest/batches" -Headers $Headers -Body $batchBody
$batchId = $batch.id
Write-Host "Batch: $batchId"

Write-Host "2) Upload + register each file"
for ($i = 0; $i -lt $payloads.upload_url_requests.Count; $i++) {
  $uploadSpec = $payloads.upload_url_requests[$i]
  $registerSpec = $payloads.register_requests[$i]

  $baseBlobPath = $uploadSpec.body.blob_path
  if ($baseBlobPath -match '^(.*?)(\.[^./\\]+)$') {
    $blobPath = $Matches[1] + "-$runStamp" + $Matches[2]
  } else {
    $blobPath = "$baseBlobPath-$runStamp"
  }

  $localFilename = $uploadSpec.local_filename
  $filePath = Join-Path $PSScriptRoot $localFilename
  if (-not (Test-Path -LiteralPath $filePath)) {
    throw "File not found: $filePath"
  }

  Write-Host "- Generating SAS for $localFilename"
  $uploadBody = (@{
      container_name = $uploadSpec.body.container_name
      blob_path = $blobPath
      content_type = $uploadSpec.body.content_type
    } | ConvertTo-Json -Depth 10)
  $upload = Invoke-RestMethodVerboseError -Method Post -Uri "$BASE_URL/v1/ingest/batches/$batchId/upload-urls?tenant_id=$tenantId" -Headers $Headers -Body $uploadBody

  Write-Host "  Uploading $localFilename"
  Invoke-WebRequest -UseBasicParsing -Method Put -Uri $upload.upload_sas_url -InFile $filePath -Headers @{ "x-ms-blob-type"="BlockBlob"; "Content-Type"=$uploadSpec.body.content_type } | Out-Null

  Write-Host "  Registering $localFilename"
  $versionLabel = $registerSpec.body.version_label
  if ($null -ne $versionLabel -and $versionLabel -ne "") {
    $versionLabel = "$versionLabel-$runStamp"
  }

  $metadata = @{}
  if ($registerSpec.body.metadata) {
    foreach ($p in $registerSpec.body.metadata.PSObject.Properties) {
      $metadata[$p.Name] = $p.Value
    }
  }
  $metadata["run_id"] = $runStamp

  $registerBody = (@{
      container_name = $registerSpec.body.container_name
      blob_path = $blobPath
      policy_external_id = $registerSpec.body.policy_external_id
      policy_name = $registerSpec.body.policy_name
      version_label = $versionLabel
      effective_date = $registerSpec.body.effective_date
      title = $registerSpec.body.title
      metadata = $metadata
      correlation_id = ("{0}-{1}" -f $registerSpec.body.correlation_id, $runStamp)
    } | ConvertTo-Json -Depth 10)
  $reg = Invoke-RestMethodVerboseError -Method Post -Uri "$BASE_URL/v1/ingest/batches/$batchId/register?tenant_id=$tenantId" -Headers $Headers -Body $registerBody
  Write-Host "    policy_version_id=$($reg.policy_version_id) parse_status=$($reg.parse_status)"
}

Write-Host "Done. You can now check:"
Write-Host "- GET $BASE_URL/v1/ingest/batches/$batchId?tenant_id=$tenantId"
Write-Host "- GET $BASE_URL/v1/policies?tenant_id=$tenantId"

$BASE_URL = "http://localhost:8000"
$TENANT_ID = "00000000-0000-0000-0000-000000000001"
$Headers = @{ "Content-Type" = "application/json" }

$ErrorActionPreference = "Stop"

$RAW_CONTAINER = "policy-raw"

# This script lives in policyDocs/demoScripts, but the input file lives in policyDocs/
$policyDocsRoot = Split-Path -Parent $PSScriptRoot
$FilePath = Join-Path $policyDocsRoot "sample_text_v1.txt"
if (-not (Test-Path -LiteralPath $FilePath)) { throw "Missing file: $FilePath" }
Write-Host "Using file: $FilePath"

function Read-HttpErrorBody {
  param([Parameter(Mandatory=$true)]$ErrorRecord)
  try {
    if ($ErrorRecord.ErrorDetails -and $ErrorRecord.ErrorDetails.Message) {
      return $ErrorRecord.ErrorDetails.Message
    }
    if ($ErrorRecord.Exception -and $ErrorRecord.Exception.Response) {
      $resp = $ErrorRecord.Exception.Response
      $sr = New-Object System.IO.StreamReader($resp.GetResponseStream())
      $body = $sr.ReadToEnd()
      $sr.Close()
      return $body
    }
  } catch { }
  return $null
}

function Normalize-ItemsArray {
  param([Parameter(Mandatory=$true)]$Raw)
  if ($null -eq $Raw) { return @() }
  if ($Raw.PSObject.Properties.Name -contains "items") { return @($Raw.items) }
  if ($Raw -is [System.Array]) { return $Raw }
  return @($Raw)
}

function Find-PolicyByExternalId {
  param([Parameter(Mandatory=$true)][string]$ExternalId)

  $policiesRaw = Invoke-RestMethod -Method Get -Uri "$BASE_URL/v1/policies?tenant_id=$TENANT_ID" -Headers $Headers
  $policies = Normalize-ItemsArray -Raw $policiesRaw
  return ($policies | Where-Object { $_.external_id -eq $ExternalId } | Select-Object -First 1)
}

function Find-PolicyVersionIdByLabel {
  param(
    [Parameter(Mandatory=$true)][string]$PolicyId,
    [Parameter(Mandatory=$true)][string]$VersionLabel
  )

  $versionsRaw = Invoke-RestMethod -Method Get -Uri "$BASE_URL/v1/policies/$PolicyId/versions?tenant_id=$TENANT_ID" -Headers $Headers
  $versions = Normalize-ItemsArray -Raw $versionsRaw
  $match = $versions | Where-Object { $_.version_label -eq $VersionLabel } | Select-Object -First 1
  if ($match) { return $match.id }
  return $null
}

# If policy/version already exists, do not create new blobs/versions.
$EXTERNAL_ID = "sample-conflict-doc"
$VERSION_LABEL = "v1"

$existingPolicy = Find-PolicyByExternalId -ExternalId $EXTERNAL_ID
$policyId = $null
$policyVersionId = $null

if ($existingPolicy -and $existingPolicy.id) {
  $policyId = $existingPolicy.id
  $policyVersionId = Find-PolicyVersionIdByLabel -PolicyId $policyId -VersionLabel $VERSION_LABEL
  if ($policyVersionId) {
    Write-Host "[INFO] Found existing policy/version; skipping upload+register." -ForegroundColor Yellow
    Write-Host "Using policy_id=$policyId policy_version_id=$policyVersionId" -ForegroundColor Yellow
  }
}

if (-not $policyId -or -not $policyVersionId) {
  # 1) Create batch
  $batchBody = (@{ tenant_id=$TENANT_ID; source_system="conflict-test"; correlation_id="conflict-sample-v1" } | ConvertTo-Json)
  $batch = Invoke-RestMethod -Method Post -Uri "$BASE_URL/v1/ingest/batches" -Headers $Headers -Body $batchBody
  $batchId = $batch.id
  Write-Host "Batch: $batchId"

  # 2) Get SAS URL (use a stable blob path so reruns don't generate new files)
  $blobPath = "documents/conflict/sample_text_v1.txt"
  $uploadBody = (@{ container_name=$RAW_CONTAINER; blob_path=$blobPath; content_type="text/plain"; expires_in_minutes=30 } | ConvertTo-Json)
  $upload = Invoke-RestMethod -Method Post -Uri "$BASE_URL/v1/ingest/batches/$batchId/upload-urls?tenant_id=$TENANT_ID" -Headers $Headers -Body $uploadBody
  Write-Host "Uploading to: $($upload.blob_uri)"

  # 3) Upload blob
  Invoke-WebRequest -UseBasicParsing -Method Put -Uri $upload.upload_sas_url -InFile $FilePath -Headers @{
    "x-ms-blob-type"="BlockBlob"
    "Content-Type"="text/plain"
  } | Out-Null

  # 4) Register
  $registerBody = @{
    container_name=$RAW_CONTAINER
    blob_path=$blobPath
    policy_external_id=$EXTERNAL_ID
    policy_name="Sample Conflict Reference"
    version_label=$VERSION_LABEL
    effective_date="2026-03-03"
    title="Sample Conflict Reference v1"
    correlation_id="conflict-sample-v1"
    metadata=@{
      authority_level=80
      department_scope="all"
      policy_type="general"
      test_case="conflict_selection"
    }
  } | ConvertTo-Json -Depth 10

  $handledDuplicate = $false

  try {
    $reg = Invoke-RestMethod -Method Post -Uri "$BASE_URL/v1/ingest/batches/$batchId/register?tenant_id=$TENANT_ID" -Headers $Headers -Body $registerBody
    $policyId = $reg.policy_id
    $policyVersionId = $reg.policy_version_id
    Write-Host "Registered policy_version_id=$policyVersionId parse_status=$($reg.parse_status)"
  }
  catch {
    $body = Read-HttpErrorBody -ErrorRecord $_
    if ($body) {
      try {
        $errObj = $body | ConvertFrom-Json
        if ($errObj.detail -and $errObj.detail.code -eq "DUPLICATE_VERSION" -and $errObj.detail.existing_policy_version_id) {
          $policyVersionId = $errObj.detail.existing_policy_version_id
          $existingPolicy = Find-PolicyByExternalId -ExternalId $EXTERNAL_ID
          if (-not $existingPolicy -or -not $existingPolicy.id) { throw "Could not locate policy_id for external_id=$EXTERNAL_ID" }
          $policyId = $existingPolicy.id
          Write-Host "[WARN] Duplicate version; reusing policy_id=$policyId existing_policy_version_id=$policyVersionId" -ForegroundColor Yellow
          $handledDuplicate = $true
        }
      } catch { }
      if (-not $handledDuplicate) {
        Write-Host "--- register error body ---" -ForegroundColor Red
        Write-Host $body
      }
    }
    if (-not $handledDuplicate) { throw }
  }
}

if (-not $policyId -or -not $policyVersionId) {
  throw "Could not determine policy_id/policy_version_id."
}

# 5) Poll versions until ready (up to 10 minutes)
$deadline = (Get-Date).AddMinutes(10)
do {
  Start-Sleep -Seconds 10
  $versionsRaw = Invoke-RestMethod -Method Get -Uri "$BASE_URL/v1/policies/$policyId/versions?tenant_id=$TENANT_ID" -Headers $Headers
  $versions = Normalize-ItemsArray -Raw $versionsRaw
  $v = $versions | Where-Object { $_.id -eq $policyVersionId } | Select-Object -First 1
  $status = $v.parse_status
  Write-Host ("status={0} at {1}" -f $status, (Get-Date).ToString("HH:mm:ss"))
  if ($status -eq "failed") { throw "Extraction failed: $($v.parse_error_code) $($v.parse_error_message)" }
} while ($status -ne "ready" -and (Get-Date) -lt $deadline)

if ($status -ne "ready") { throw "Timed out waiting for ready." }

# 6) Verify sections
$sections = Invoke-RestMethod -Method Get -Uri "$BASE_URL/v1/policy-versions/$policyVersionId/sections?tenant_id=$TENANT_ID&limit=50" -Headers $Headers
$match = $sections | Where-Object { $_.text -match "60 days" } | Select-Object -First 1
if (-not $match) { throw "No '60 days' section found." }

Write-Host "[PASS] Sample reference document ingested and extracted."
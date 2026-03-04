# Phase 2 demo + test runner
# - Ingests docs (same flow as your Phase 1 runner)
# - Then validates Phase 2: /ask -> /audit -> /replay
# Usage:
#   powershell -ExecutionPolicy Bypass -File .\run_phase2_tests.ps1
# Requirements:
#   - example_api_payloads.json exists in same folder
#   - your API is running at BASE_URL

$BASE_URL = "http://localhost:8000"
$Headers = @{ "Content-Type" = "application/json" }

$POLL_SECONDS = 2
$POLL_MAX_TRIES = 300

function Invoke-RestMethodVerboseError {
  param(
    [Parameter(Mandatory=$true)][string]$Method,
    [Parameter(Mandatory=$true)][string]$Uri,
    [Parameter(Mandatory=$false)][hashtable]$Headers,
    [Parameter(Mandatory=$false)][string]$Body
  )

  try {
    $hasBody = $PSBoundParameters.ContainsKey("Body") -and ($null -ne $Body) -and ($Body -ne "")
    if ($hasBody) {
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
      } catch { }
    }

    throw
  }
}

function Get-FirstNonNull {
  param(
    [Parameter(Mandatory=$true)]$Obj,
    [Parameter(Mandatory=$true)][string[]]$Keys
  )
  foreach ($k in $Keys) {
    if ($null -ne $Obj.$k -and $Obj.$k -ne "") { return $Obj.$k }
  }
  return $null
}

function Assert-True {
  param(
    [Parameter(Mandatory=$true)][bool]$Condition,
    [Parameter(Mandatory=$true)][string]$Message
  )
  if (-not $Condition) {
    Write-Host ("[FAIL] {0}" -f $Message) -ForegroundColor Red
    throw $Message
  } else {
    Write-Host ("[PASS] {0}" -f $Message) -ForegroundColor Green
  }
}

function Write-Section {
  param([string]$Title)
  Write-Host ""
  Write-Host ("==== {0} ====" -f $Title) -ForegroundColor Cyan
}

function Upload-BlobWithSas {
  param(
    [Parameter(Mandatory=$true)][string]$SasUrl,
    [Parameter(Mandatory=$true)][string]$FilePath,
    [Parameter(Mandatory=$true)][string]$ContentType,
    [int]$MaxRetries = 5,
    [int]$RetrySeconds = 2
  )

  for ($try = 0; $try -lt $MaxRetries; $try++) {
    try {
      $resp = Invoke-WebRequest -UseBasicParsing -Method Put -Uri $SasUrl -InFile $FilePath -Headers @{
        "x-ms-blob-type"="BlockBlob"
        "Content-Type"=$ContentType
      } -ErrorAction Stop

      if ($resp.StatusCode -ne 201) {
        throw "Upload failed. Expected HTTP 201, got $($resp.StatusCode)"
      }
      return
    }
    catch [System.IO.IOException] {
      if ($try -lt ($MaxRetries - 1)) {
        Write-Host ("[WARN] File is locked, retrying in {0}s: {1}" -f $RetrySeconds, $FilePath) -ForegroundColor Yellow
        Start-Sleep -Seconds $RetrySeconds
        continue
      }
      throw "Local file is locked (in use by another process). Close it and re-run. File: $FilePath"
    }
  }
}

# --------------------------
# Load payloads + settings
# --------------------------
$payloadPath = Join-Path $PSScriptRoot "example_api_payloads.json"
if (-not (Test-Path -LiteralPath $payloadPath)) {
  throw "Missing file: $payloadPath"
}

$payloads = Get-Content -Raw -Path $payloadPath | ConvertFrom-Json
$tenantId = $payloads.tenant_id
if (-not $tenantId) { $tenantId = "00000000-0000-0000-0000-000000000001" }

$runStamp = Get-Date -Format "yyyyMMdd-HHmmss"
Write-Host ("Run ID: {0}" -f $runStamp)

# --------------------------
# Phase 1: Ingest docs
# --------------------------
Write-Section "Phase 1 - Ingest"

Write-Host "1) Create ingest batch"
$batchBody = ($payloads.create_batch | ConvertTo-Json -Depth 20)
$batch = Invoke-RestMethodVerboseError -Method Post -Uri "$BASE_URL/v1/ingest/batches" -Headers $Headers -Body $batchBody
$batchId = Get-FirstNonNull -Obj $batch -Keys @("id","batch_id","ingest_batch_id","ingestBatchId")
Assert-True -Condition ([bool]$batchId) -Message "Create batch returned batchId"
Write-Host ("Batch: {0}" -f $batchId)

Write-Host "2) Upload + register each file"
$registered = @()
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
  Assert-True -Condition (Test-Path -LiteralPath $filePath) -Message "Local file exists: $localFilename"

  Write-Host "- Generating SAS for $localFilename"
  $uploadBody = (@{
      container_name = $uploadSpec.body.container_name
      blob_path       = $blobPath
      content_type    = $uploadSpec.body.content_type
    } | ConvertTo-Json -Depth 10)

  $upload = Invoke-RestMethodVerboseError -Method Post -Uri "$BASE_URL/v1/ingest/batches/$batchId/upload-urls?tenant_id=$tenantId" -Headers $Headers -Body $uploadBody
  $sasUrl = Get-FirstNonNull -Obj $upload -Keys @("upload_sas_url","sas_url","sasUrl")
  $blobUri = Get-FirstNonNull -Obj $upload -Keys @("blob_uri","blobUri","blob_url","blobUrl")

  Assert-True -Condition ([bool]$sasUrl) -Message "SAS URL returned for $localFilename"

  Write-Host "  Uploading $localFilename"
  Upload-BlobWithSas -SasUrl $sasUrl -FilePath $filePath -ContentType $uploadSpec.body.content_type

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
      container_name      = $registerSpec.body.container_name
      blob_path           = $blobPath
      policy_external_id  = $registerSpec.body.policy_external_id
      policy_name         = $registerSpec.body.policy_name
      version_label       = $versionLabel
      effective_date      = $registerSpec.body.effective_date
      title               = $registerSpec.body.title
      metadata            = $metadata
      correlation_id      = ("{0}-{1}" -f $registerSpec.body.correlation_id, $runStamp)
    } | ConvertTo-Json -Depth 20)

  $reg = Invoke-RestMethodVerboseError -Method Post -Uri "$BASE_URL/v1/ingest/batches/$batchId/register?tenant_id=$tenantId" -Headers $Headers -Body $registerBody

  $pvId = Get-FirstNonNull -Obj $reg -Keys @("policy_version_id","policyVersionId","id")
  $policyId  = Get-FirstNonNull -Obj $reg -Keys @("policy_id","policyId")
  $ps   = Get-FirstNonNull -Obj $reg -Keys @("parse_status","parseStatus","status")
  Write-Host ("    policy_version_id={0} parse_status={1}" -f $pvId, $ps)

  if ($policyId -and $pvId) {
    $registered += [pscustomobject]@{ policy_id = $policyId; policy_version_id = $pvId; file = $localFilename }
  }
}

Write-Host "3) Check batch status endpoint (optional)"
Write-Host ("   GET {0}/v1/ingest/batches/{1}?tenant_id={2}" -f $BASE_URL, $batchId, $tenantId)

function Wait-PolicyReady {
  param(
    [Parameter(Mandatory=$true)][string]$PolicyId
  )

  for ($i = 0; $i -lt $POLL_MAX_TRIES; $i++) {
    $raw = Invoke-RestMethodVerboseError -Method Get -Uri "$BASE_URL/v1/policies/$PolicyId/versions?tenant_id=$tenantId" -Headers $Headers

    $versions = $raw
    if ($null -ne $raw -and ($raw.PSObject.Properties.Name -contains "items")) {
      $versions = $raw.items
    }
    if ($null -ne $versions -and -not ($versions -is [System.Array])) {
      $versions = @($versions)
    }

    if ($null -eq $versions -or $versions.Count -lt 1) {
      Start-Sleep -Seconds $POLL_SECONDS
      continue
    }

    $readyCurrent = $versions |
      Where-Object {
        $s = Get-FirstNonNull -Obj $_ -Keys @("parse_status","parseStatus","status")
        if ($s -ne "ready") { return $false }
        if ($_.PSObject.Properties.Name -contains "is_current") {
          return ($_.is_current -eq $true)
        }
        return $true
      } |
      Select-Object -First 1

    if ($null -ne $readyCurrent) { return $readyCurrent }

    $failed = $versions |
      Where-Object { (Get-FirstNonNull -Obj $_ -Keys @("parse_status","parseStatus","status")) -eq "failed" } |
      Select-Object -First 1
    if ($null -ne $failed) { throw "Policy version failed extraction for policy_id=$PolicyId" }

    $probe = $versions[0]
    $status = Get-FirstNonNull -Obj $probe -Keys @("parse_status","parseStatus","status")
    $isCurrent = $null
    if ($probe.PSObject.Properties.Name -contains "is_current") { $isCurrent = $probe.is_current }
    Write-Host ("poll {0} policy_id={1} status={2} is_current={3}" -f $i, $PolicyId, $status, $isCurrent)

    Start-Sleep -Seconds $POLL_SECONDS
  }

  throw "Timed out waiting for policy_id=$PolicyId to become ready"
}

Write-Host "4) Wait for extraction (policy versions -> ready)"
$uniquePolicyIds = @()
if ($registered -and $registered.Count -gt 0) {
  $uniquePolicyIds = $registered | Select-Object -ExpandProperty policy_id -Unique
}

foreach ($policyId in $uniquePolicyIds) {
  Write-Host ("Waiting for policy_id={0}" -f $policyId)
  Wait-PolicyReady -PolicyId $policyId | Out-Null
}

# --------------------------
# Phase 2: Ask/Audit/Replay tests
# --------------------------
Write-Section "Phase 2 - Ask/Audit/Replay"

function Invoke-Ask {
  param(
    [string]$Question,
    [string]$Department,
    [string[]]$PolicyTypes = $null,
    [bool]$OnlyCurrent = $true
  )

  $scopeObj = @{ only_current = $OnlyCurrent }
  if ($PolicyTypes) { $scopeObj["policy_types"] = $PolicyTypes }

  $askBody = @{
    tenant_id = $tenantId
    question  = $Question
    mode      = "strict"
    user      = @{
      tenant_id  = $tenantId
      email      = "dev@local"
      role       = "user"
      department = $Department
    }
    scope     = $scopeObj
  } | ConvertTo-Json -Depth 20

  return Invoke-RestMethodVerboseError -Method Post -Uri "$BASE_URL/v1/ask" -Headers $Headers -Body $askBody
}

# Test 1: Golden path
Write-Host "T1) Golden path - should return citations"
$r1 = Invoke-Ask -Question "What is the deadline to file an appeal?" -Department "claims_ops" -PolicyTypes @("claims") -OnlyCurrent $true

$cit1 = $r1.citations
$audit1 = Get-FirstNonNull -Obj $r1 -Keys @("audit_id","auditId")
Assert-True -Condition ([bool]$audit1) -Message "Ask returns auditId"
if ($null -eq $cit1 -or $cit1.Count -lt 1) {
  Write-Host "Ask returned 0 citations; dumping response for debugging:" -ForegroundColor Yellow
  Write-Host ($r1 | ConvertTo-Json -Depth 20)
}
Assert-True -Condition ($null -ne $cit1 -and $cit1.Count -ge 1) -Message "Ask returns >= 1 citation"
Write-Host ("Answer: {0}" -f $r1.answer)

# Test 2: Audit read
Write-Host "T2) Audit read"
$auditUrl = ("{0}/v1/audit/{1}?tenant_id={2}" -f $BASE_URL, $audit1, $tenantId)
$a2 = Invoke-RestMethodVerboseError -Method Get -Uri $auditUrl -Headers $Headers
Assert-True -Condition ($null -ne $a2) -Message "Audit GET returns payload"

# Test 3: Replay
Write-Host "T3) Replay"
$replayUrl = ("{0}/v1/audit/{1}/replay?tenant_id={2}" -f $BASE_URL, $audit1, $tenantId)
$rep = Invoke-RestMethodVerboseError -Method Post -Uri $replayUrl -Headers $Headers
Assert-True -Condition ($null -ne $rep) -Message "Replay returns payload"

# Test 4: Conflict/department behavior (expect either different citations OR warning behavior)
Write-Host "T4) Department variation"
$rClaims = Invoke-Ask -Question "What is the deadline to file an appeal?" -Department "claims_ops" -OnlyCurrent $true
$rPriv   = Invoke-Ask -Question "What is the deadline to file an appeal?" -Department "privacy_office" -OnlyCurrent $true

$claimsCiteFirst = $null
$privCiteFirst = $null
if ($rClaims.citations -and $rClaims.citations.Count -gt 0) { $claimsCiteFirst = ($rClaims.citations[0] | ConvertTo-Json -Compress) }
if ($rPriv.citations -and $rPriv.citations.Count -gt 0)   { $privCiteFirst   = ($rPriv.citations[0] | ConvertTo-Json -Compress) }

if ($claimsCiteFirst -and $privCiteFirst -and ($claimsCiteFirst -ne $privCiteFirst)) {
  Write-Host "[PASS] Department affects chosen evidence (citations differ)" -ForegroundColor Green
} else {
  Write-Host "[WARN] Citations did not differ. This may be OK if your policy rules allow fallback." -ForegroundColor Yellow
  Write-Host ("claims citations: {0}" -f ($rClaims.citations | ConvertTo-Json -Depth 5))
  Write-Host ("privacy citations: {0}" -f ($rPriv.citations | ConvertTo-Json -Depth 5))
}

# Test 5: Refusal path (should refuse with insufficient evidence)
Write-Host "T5) Refusal path"
$r5 = Invoke-Ask -Question "What is the dental reimbursement cap for 2027?" -Department "claims_ops" -OnlyCurrent $true
Assert-True -Condition ($r5.refusal_reason -ne $null -and $r5.refusal_reason -ne "") -Message "Refusal_reason returned for unsupported question"
Assert-True -Condition ($r5.citations -eq $null -or $r5.citations.Count -eq 0) -Message "Refusal returns 0 citations"
Write-Host ("Refusal: {0}" -f $r5.refusal_reason)

Write-Section "Done"
Write-Host "Batch created: $batchId"
Write-Host "Audit sample: $audit1"
Write-Host ("Swagger: {0}/docs" -f $BASE_URL)
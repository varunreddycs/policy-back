param(
    [string]$BaseUrl = "http://localhost:8000",
    [string]$TenantId = "00000000-0000-0000-0000-000000000001",

    [string]$PolicyExternalId = "DOC_SET_A",
    [string]$PolicyName = "Sample Governance Document (Demo)",
    [string]$VersionLabel = "v1",

    [hashtable]$Metadata = @{ department = "operations"; sensitivity = "internal"; type = "general" },

    [int]$PollSeconds = 2,
    [int]$PollMaxTries = 30,
    [int]$SectionsLimit = 5,

    [switch]$ShowDedupe,
    [switch]$ShowVersionLabelConflict
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Assert-ApiUp {
    param([string]$BaseUrl)
    try {
        $resp = Invoke-WebRequest -UseBasicParsing -Uri ("{0}/openapi.json" -f $BaseUrl) -Method Get
        if ($resp.StatusCode -ne 200) {
            throw "API returned status code $($resp.StatusCode)"
        }
    } catch {
        throw "API not reachable at $BaseUrl. Start it with: python -m uvicorn app:app --reload --env-file .env"
    }
}

function To-Json {
    param($Obj)
    return ($Obj | ConvertTo-Json -Depth 20)
}

function New-DemoText {
    param(
        [string]$Suffix,
        [string]$RunId
    )
    return @"
$PolicyName $Suffix

RunId: $RunId

1. Purpose
This is a demo policy used to exercise the pipeline.

2. Scope
Applies to all staff handling internal documentation.

3. Controls
- Access logging
- Controlled usage and retention
"@
}

function Invoke-Rest {
    param(
        [string]$Method,
        [string]$Uri,
        $Body = $null
    )
    if ($null -eq $Body) {
        return Invoke-RestMethod -Method $Method -Uri $Uri
    }
    return Invoke-RestMethod -Method $Method -Uri $Uri -ContentType "application/json" -Body ($Body | ConvertTo-Json -Depth 20)
}

function Try-ParseErrorDetailJson {
    param($ErrorRecord)
    try {
        $msg = $ErrorRecord.ErrorDetails.Message
        if (-not $msg) { return $null }
        return ($msg | ConvertFrom-Json)
    } catch {
        return $null
    }
}

function Upload-BlobWithSas {
    param(
        [string]$SasUrl,
        [string]$FilePath,
        [string]$ContentType
    )
    $headers = @{ "x-ms-blob-type" = "BlockBlob"; "Content-Type" = $ContentType }
    $resp = Invoke-WebRequest -UseBasicParsing -Uri $SasUrl -Method Put -InFile $FilePath -Headers $headers
    if ($resp.StatusCode -ne 201) {
        throw "Upload failed. Expected 201, got $($resp.StatusCode)"
    }
}

function Poll-VersionReady {
    param(
        [string]$BaseUrl,
        [string]$TenantId,
        [string]$PolicyId,
        [int]$PollSeconds,
        [int]$PollMaxTries
    )

    for ($i = 0; $i -lt $PollMaxTries; $i++) {
        $versions = Invoke-Rest -Method Get -Uri ("{0}/v1/policies/{1}/versions?tenant_id={2}" -f $BaseUrl, $PolicyId, $TenantId)
        if ($null -eq $versions -or $versions.Count -lt 1) {
            Start-Sleep -Seconds $PollSeconds
            continue
        }

        $latest = $versions[0]
        $status = $latest.parse_status
        Write-Host ("poll {0} status={1}" -f $i, $status)

        if ($status -eq "ready") {
            return $latest
        }
        if ($status -eq "failed") {
            throw ("Extraction failed: {0} {1}" -f $latest.parse_error_code, $latest.parse_error_message)
        }

        Start-Sleep -Seconds $PollSeconds
    }

    throw "Timed out waiting for parse_status=ready"
}

Assert-ApiUp -BaseUrl $BaseUrl

$artifactsDir = Join-Path $PSScriptRoot "demo_artifacts"
if (-not (Test-Path -LiteralPath $artifactsDir)) {
    New-Item -ItemType Directory -Path $artifactsDir | Out-Null
}

# 1) Create ingestion batch
$batch = Invoke-Rest -Method Post -Uri ("{0}/v1/ingest/batches" -f $BaseUrl) -Body @{ tenant_id = $TenantId }
$batchId = $batch.id

# 2) Get SAS upload URL
$stamp = (Get-Date).ToString("yyyyMMdd-HHmmss")
$blobPath = "policies/demo/{0}-{1}.txt" -f ($PolicyExternalId.ToLower()), $stamp
$upload = Invoke-Rest -Method Post -Uri ("{0}/v1/ingest/batches/{1}/upload-urls?tenant_id={2}" -f $BaseUrl, $batchId, $TenantId) -Body @{ container_name = "policy-raw"; blob_path = $blobPath; content_type = "text/plain" }

# 3) Upload demo text
$tmpFile = Join-Path $artifactsDir ("tmp_demo_policy_{0}.txt" -f $stamp)
Set-Content -Path $tmpFile -Value (New-DemoText -Suffix "(v1)" -RunId $stamp) -Encoding UTF8
Upload-BlobWithSas -SasUrl $upload.upload_sas_url -FilePath $tmpFile -ContentType "text/plain"

# 4) Register the blob
$registerPayload = @{ 
    container_name = "policy-raw"
    blob_path = $blobPath
    policy_external_id = $PolicyExternalId
    policy_name = $PolicyName
    version_label = $VersionLabel
    metadata = $Metadata
}

$registerUri = ("{0}/v1/ingest/batches/{1}/register?tenant_id={2}" -f $BaseUrl, $batchId, $TenantId)
try {
    $registered = Invoke-Rest -Method Post -Uri $registerUri -Body $registerPayload
} catch {
    $detail = Try-ParseErrorDetailJson -ErrorRecord $_
    $code = $null
    if ($detail -and $detail.detail -and $detail.detail.code) { $code = $detail.detail.code }
    if ($code -eq "VERSION_LABEL_CONFLICT" -and $registerPayload.version_label) {
        $newLabel = ("{0}-{1}" -f $registerPayload.version_label, $stamp)
        Write-Host ("version_label conflict; retrying with '{0}'" -f $newLabel)
        $registerPayload.version_label = $newLabel
        $registered = Invoke-Rest -Method Post -Uri $registerUri -Body $registerPayload
    } else {
        throw
    }
}

$policyId = $registered.policy_id
$policyVersionId = $registered.policy_version_id

# 5) Poll until ready
$ready = Poll-VersionReady -BaseUrl $BaseUrl -TenantId $TenantId -PolicyId $policyId -PollSeconds $PollSeconds -PollMaxTries $PollMaxTries

# 6) Fetch top sections
$sectionsUri = "{0}/v1/policy-versions/{1}/sections?tenant_id={2}&limit={3}" -f $BaseUrl, $policyVersionId, $TenantId, $SectionsLimit
$sections = Invoke-Rest -Method Get -Uri $sectionsUri

# Summary
$summary = [ordered]@{
    tenant_id = $TenantId
    batch_id = $batchId
    policy_id = $policyId
    policy_version_id = $policyVersionId
    version_number = $registered.version_number
    version_label = $ready.version_label
    content_sha256 = $registered.content_sha256
    metadata_sha256 = $registered.metadata_sha256
    raw_blob_uri = $ready.raw_blob_uri
    extracted_blob_uri = $ready.extracted_blob_uri
    is_current = $ready.is_current
    parse_status = $ready.parse_status
    sections_returned = @($sections).Count
    sample_section_title = if (@($sections).Count -gt 0) { $sections[0].title } else { $null }
}

"demo_phase1.summary" | Write-Host
To-Json $summary | Write-Host

if ($ShowDedupe) {
    "demo_phase1.dedupe" | Write-Host
    $batch2 = Invoke-Rest -Method Post -Uri ("{0}/v1/ingest/batches" -f $BaseUrl) -Body @{ tenant_id = $TenantId }
    $batch2Id = $batch2.id

    try {
        $null = Invoke-Rest -Method Post -Uri ("{0}/v1/ingest/batches/{1}/register?tenant_id={2}" -f $BaseUrl, $batch2Id, $TenantId) -Body $registerPayload
        "Expected 409 DUPLICATE_VERSION, but request succeeded" | Write-Host
    } catch {
        $detail = $_.ErrorDetails.Message
        if (-not $detail) { $detail = $_.Exception.Message }
        $detail | Write-Host
    }
}

if ($ShowVersionLabelConflict) {
    "demo_phase1.version_label_conflict" | Write-Host

    $batch3 = Invoke-Rest -Method Post -Uri ("{0}/v1/ingest/batches" -f $BaseUrl) -Body @{ tenant_id = $TenantId }
    $batch3Id = $batch3.id

    $blobPath2 = "policies/demo/{0}-{1}-alt.txt" -f ($PolicyExternalId.ToLower()), $stamp
    $upload2 = Invoke-Rest -Method Post -Uri ("{0}/v1/ingest/batches/{1}/upload-urls?tenant_id={2}" -f $BaseUrl, $batch3Id, $TenantId) -Body @{ container_name = "policy-raw"; blob_path = $blobPath2; content_type = "text/plain" }

    $tmpFile2 = Join-Path $artifactsDir ("tmp_demo_policy_{0}_alt.txt" -f $stamp)
    Set-Content -Path $tmpFile2 -Value (New-DemoText -Suffix "(different content)" -RunId ("{0}-alt" -f $stamp)) -Encoding UTF8
    Upload-BlobWithSas -SasUrl $upload2.upload_sas_url -FilePath $tmpFile2 -ContentType "text/plain"

    $registerPayload2 = $registerPayload.Clone()
    $registerPayload2.blob_path = $blobPath2

    try {
        $null = Invoke-Rest -Method Post -Uri ("{0}/v1/ingest/batches/{1}/register?tenant_id={2}" -f $BaseUrl, $batch3Id, $TenantId) -Body $registerPayload2
        "Expected 409 VERSION_LABEL_CONFLICT, but request succeeded" | Write-Host
    } catch {
        $detail = $_.ErrorDetails.Message
        if (-not $detail) { $detail = $_.Exception.Message }
        $detail | Write-Host
    }
}

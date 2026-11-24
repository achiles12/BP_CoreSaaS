<#
  Wireframe PDF: manual check from the Windows PC (01_design/wireframes/20261113_wireframe_manual_test.md).
  Copies 01_design/wireframe.pdf and its SHA-256 from the dev host with scp (built into
  Windows 10/11 OpenSSH), verifies it, then opens it in the default PDF viewer.

  Usage:
    powershell -ExecutionPolicy Bypass -File .\20261113_wireframe_manual_test.ps1 -SshUser <your-login>
  Options:
    -Server  dev host (default 192.168.50.113)
    -NoOpen  do not open the PDF at the end
#>
param(
  [Parameter(Mandatory = $true)][string]$SshUser,
  [string]$Server = "192.168.50.113",
  [string]$RepoPath = "/prj/coruscant/daffy",
  [switch]$NoOpen
)
$ErrorActionPreference = "Stop"
$Expected = 21                                   # pages: cover + map + 19 screen pages
$Dest = Join-Path $env:TEMP "daffy-wireframe"
$Pdf = Join-Path $Dest "wireframe.pdf"
$Sha = Join-Path $Dest "wireframe.pdf.sha256"
$script:Pass = 0; $script:Fail = 0

function Check([string]$Id, [string]$Desc, [scriptblock]$Test) {
  try {
    $ok = & $Test
    if ($ok) { $script:Pass++; Write-Host "PASS $Id $Desc" -ForegroundColor Green }
    else { $script:Fail++; Write-Host "FAIL $Id $Desc" -ForegroundColor Red }
  } catch { $script:Fail++; Write-Host "FAIL $Id $Desc :: $($_.Exception.Message)" -ForegroundColor Red }
}

New-Item -ItemType Directory -Force -Path $Dest | Out-Null
Remove-Item -Force -ErrorAction SilentlyContinue $Pdf, $Sha
Write-Host "[wf] copying from ${SshUser}@${Server} (you may be asked for your password twice)"

Check "W1" "scp copies 01_design/wireframe.pdf" {
  & scp -q "${SshUser}@${Server}:${RepoPath}/01_design/wireframe.pdf" $Pdf
  ($LASTEXITCODE -eq 0) -and (Test-Path $Pdf)
}
Check "W2" "scp copies the SHA-256 file" {
  & scp -q "${SshUser}@${Server}:${RepoPath}/01_design/wireframes/20261113_wireframe.pdf.sha256" $Sha
  ($LASTEXITCODE -eq 0) -and (Test-Path $Sha)
}
Check "W3" "SHA-256 matches the server's" {
  $want = ((Get-Content $Sha -Raw).Trim() -split '\s+')[0].ToLower()
  $got = (Get-FileHash -Algorithm SHA256 $Pdf).Hash.ToLower()
  Write-Host "     server $want`n     local  $got"
  $want -eq $got
}
# Read as Latin-1 so binary bytes map 1:1 to chars (works in PowerShell 5.1 and 7).
$raw = [System.Text.Encoding]::GetEncoding(28591).GetString([System.IO.File]::ReadAllBytes($Pdf))
Check "W4" "file starts with %PDF-" { $raw.StartsWith("%PDF-") }
Check "W5" "page count = $Expected" {
  $n = ([regex]::Matches($raw, '/Type\s*/Page(?![s\w])')).Count
  Write-Host "     pages: $n"
  $n -eq $Expected
}
Check "W6" "size between 100 KB and 10 MB" { $len = (Get-Item $Pdf).Length; ($len -gt 100KB) -and ($len -lt 10MB) }

Write-Host ""
Write-Host "Result: $script:Pass/$($script:Pass + $script:Fail) passed. PDF: $Pdf"
if (-not $NoOpen -and (Test-Path $Pdf)) {
  Write-Host "[wf] opening the PDF: continue with the checklist in 20261113_wireframe_manual_test.md section 2"
  Start-Process $Pdf
}
if ($script:Fail -gt 0) { exit 1 }

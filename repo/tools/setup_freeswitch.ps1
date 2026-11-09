# FreeSWITCH one-shot setup for oldphone-ata (run as Administrator)
# Copies dialplan/directory XML, creates recordings dir, opens firewall,
# starts the service, then verifies extension 100 and dialplan 6001.
$ErrorActionPreference = "Stop"

$Root      = "F:\projects\oldphone-ata"
$FsDir     = "C:\Program Files\FreeSWITCH"
$RecordDir = "C:\fs\recordings"
$LogFile   = Join-Path $Root "logs\fs-setup.log"
New-Item -ItemType Directory -Force -Path (Join-Path $Root "logs") | Out-Null
Start-Transcript -Path $LogFile -Force | Out-Null

function Step($msg) { Write-Host "== $msg" -ForegroundColor Cyan }
function Ok($msg)   { Write-Host "   OK  $msg" -ForegroundColor Green }

$principal = New-Object Security.Principal.WindowsPrincipal(
    [Security.Principal.WindowsIdentity]::GetCurrent())
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Write-Host "ERROR: not running as Administrator." -ForegroundColor Red
    Stop-Transcript | Out-Null
    exit 2
}

Step "1/6 copy config XML into FreeSWITCH"
Copy-Item (Join-Path $Root "freeswitch\100.xml")          (Join-Path $FsDir "conf\directory\default\100.xml") -Force
Copy-Item (Join-Path $Root "freeswitch\01_oldphone.xml")  (Join-Path $FsDir "conf\dialplan\default\01_oldphone.xml") -Force
Ok "100.xml + 01_oldphone.xml copied"

Step "2/6 recordings directory and ACL"
New-Item -ItemType Directory -Force -Path $RecordDir | Out-Null
icacls $RecordDir /grant "*S-1-5-32-545:(OI)(CI)M" /T | Out-Null
Ok "$RecordDir ready (Users: Modify)"

Step "3/6 firewall rules (UDP 5060, 16384-32768)"
foreach ($rule in @(
    @{ Name = "FreeSWITCH SIP 5060"; Port = "5060" },
    @{ Name = "FreeSWITCH RTP 16384-32768"; Port = "16384-32768" })) {
    if (Get-NetFirewallRule -DisplayName $rule.Name -ErrorAction SilentlyContinue) {
        Ok ("rule exists: " + $rule.Name)
    } else {
        New-NetFirewallRule -DisplayName $rule.Name -Direction Inbound -Action Allow `
            -Protocol UDP -LocalPort $rule.Port -Profile Any | Out-Null
        Ok ("rule added: " + $rule.Name)
    }
}

Step "4/6 start FreeSWITCH service"
Set-Service -Name FreeSWITCH -StartupType Automatic
if ((Get-Service FreeSWITCH).Status -ne "Running") { Start-Service FreeSWITCH }
$svc = Get-Service FreeSWITCH
if ($svc.Status -ne "Running") { throw "service not running: $($svc.Status)" }
Ok "service Running (Automatic)"

Step "5/6 wait for core, reload XML"
$fscli = Join-Path $FsDir "fs_cli.exe"
$deadline = (Get-Date).AddSeconds(60)
while ((Get-Date) -lt $deadline) {
    $status = & $fscli -x "status" 2>&1
    if ($status -match "UP" -and $status -notmatch "Error Connecting") { break }
    Start-Sleep -Seconds 2
}
Ok (& $fscli -x "status" 2>&1 | Select-Object -First 1)
& $fscli -x "reloadxml" | Out-Null
Ok "reloadxml done"

Step "6/6 verify extension 100 and dialplan 6001"
$userOk = (& $fscli -x "user_exists id 100 default" 2>&1) -match "true"
if ($userOk) { Ok "extension 100 exists" } else { Write-Host "   FAIL extension 100 missing" -ForegroundColor Red }
$dp = & $fscli -x "show dialplan default 6001" 2>&1
if ($dp -match "6001") { Ok "dialplan 6001 present" } else { Write-Host "   FAIL dialplan 6001 missing" -ForegroundColor Red }
& $fscli -x "sofia status" 2>&1 | Select-Object -First 8
& $fscli -x "sofia status profile internal" 2>&1 | Select-String "State|RUNNING|Calling" | Select-Object -First 3

Step "done"
Stop-Transcript | Out-Null
exit 0

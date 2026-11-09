# Deploy the oldphone dialplan (ASCII only: PowerShell 5.1 reads BOM-less files as ANSI).
$ErrorActionPreference = "Stop"
$root = "F:\projects\oldphone-ata"
$log  = Join-Path $root "logs\deploy-dialplan.log"
function Write-Log([string]$msg) {
    $line = "{0} {1}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $msg
    Write-Host $line
    Add-Content -LiteralPath $log -Value $line -Encoding UTF8
}

$src = Join-Path $root "freeswitch\oldphone.xml"
$dst = "C:\Program Files\FreeSWITCH\conf\dialplan\oldphone.xml"
$fscli = "C:\Program Files\FreeSWITCH\fs_cli.exe"

Write-Log "copy $src -> $dst"
Copy-Item -LiteralPath $src -Destination $dst -Force
Write-Log ("dest size = " + (Get-Item -LiteralPath $dst).Length)

Write-Log "reloadxml"
& $fscli -x "reloadxml" | ForEach-Object { Write-Log ("  " + $_) }

Write-Log "check hook removed"
$xml = & $fscli -x "xml_locate dialplan"
if ($xml -match "api_hangup_hook") { Write-Log "WARN api_hangup_hook still present" } else { Write-Log "OK api_hangup_hook gone" }
if ($xml -match "oldphone_record") { Write-Log "OK oldphone_record loaded" } else { Write-Log "WARN oldphone_record missing" }

Write-Log "done"

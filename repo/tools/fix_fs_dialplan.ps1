# Install the dedicated "oldphone" dialplan context and reload FreeSWITCH.
# Requires Administrator (writes to C:\Program Files\FreeSWITCH\conf).
# ASCII only on purpose: Windows PowerShell 5.1 reads .ps1 as ANSI, non-ASCII comments can break parsing.

$ErrorActionPreference = "Stop"
$src   = "F:\projects\oldphone-ata\freeswitch"
$fs    = "C:\Program Files\FreeSWITCH"
$conf  = "$fs\conf"
$fscli = "$fs\fs_cli.exe"
$log   = "F:\projects\oldphone-ata\logs\fs-dialplan-fix.log"

function Log($m) { "$(Get-Date -Format 'HH:mm:ss')  $m" | Out-File -FilePath $log -Append -Encoding utf8 }

Log "== 1/5 install user 100 and dialplan context"
Copy-Item -LiteralPath "$src\100.xml"     -Destination "$conf\directory\default\100.xml" -Force
Copy-Item -LiteralPath "$src\oldphone.xml" -Destination "$conf\dialplan\oldphone.xml" -Force
Log "   OK copied"

$old = "$conf\dialplan\default\01_oldphone.xml"
if (Test-Path -LiteralPath $old) { Remove-Item -LiteralPath $old -Force; Log "   OK removed old 01_oldphone.xml" }

Log "== 2/5 reloadxml"
& $fscli -x "reloadxml" 2>&1 | Out-File -FilePath $log -Append -Encoding utf8

Log "== 3/5 restart internal profile"
& $fscli -x "sofia profile internal restart" 2>&1 | Out-File -FilePath $log -Append -Encoding utf8
Start-Sleep -Seconds 5

Log "== 4/5 check dialplan xml contains oldphone context"
$dp = (& $fscli -x "xml_locate dialplan" 2>&1) -join "`n"
Log ("   has_context=" + ($dp -match 'name=.oldphone.'))
Log ("   has_extension=" + ($dp -match 'oldphone_record'))
Log ("   has_6001=" + ($dp -match '6001'))

Log "== 5/5 registration"
& $fscli -x "sofia status profile internal reg" 2>&1 | Out-File -FilePath $log -Append -Encoding utf8
Log "== done"

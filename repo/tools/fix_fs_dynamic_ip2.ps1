# Fix vars.xml: external_rtp_ip / external_sip_ip must be the literal preprocessor form $${local_ip_v4}
$ErrorActionPreference = 'Stop'
$vars = 'C:\Program Files\FreeSWITCH\conf\vars.xml'
$log  = 'F:\projects\oldphone-ata\repo\logs\fs-dynamic-ip.log'
function Log($m) { $line = "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') $m"; Add-Content -Path $log -Value $line -Encoding UTF8; Write-Host $line }

$text = [IO.File]::ReadAllText($vars)
if (-not (Test-Path "$vars.bak-oldphone-ip2")) { Copy-Item $vars "$vars.bak-oldphone-ip2" }

# String.Replace is literal: single $ becomes the preprocessor-friendly $$
$text = $text.Replace('=${local_ip_v4}', '=$${local_ip_v4}')
[IO.File]::WriteAllText($vars, $text, (New-Object System.Text.UTF8Encoding($false)))
Log "vars.xml rewritten (literal dollar-dollar form)"

Select-String -Path $vars -Pattern 'external_(rtp|sip)_ip=' | ForEach-Object { Log ("file: " + $_.Line.Trim()) }

Restart-Service FreeSWITCH -Force
Start-Sleep -Seconds 12
Log "service restarted"
$fs = 'C:\Program Files\FreeSWITCH\fs_cli.exe'
& $fs -x 'reloadxml'                       | ForEach-Object { Log "reloadxml: $_" }
& $fs -x 'global_getvar external_rtp_ip'   | ForEach-Object { Log "external_rtp_ip=$_" }
& $fs -x 'sofia status'                    | ForEach-Object { Log "sofia: $_" }
$net = netstat -ano -p tcp | Select-String ':5060'
$net | ForEach-Object { Log ("net: " + $_.Line.Trim()) }
Log "done"

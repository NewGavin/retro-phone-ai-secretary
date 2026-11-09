# Make FreeSWITCH advertise the current LAN IP automatically (survives DHCP changes).
# Writes external_rtp_ip / external_sip_ip as $${local_ip_v4} and restarts the service.
$ErrorActionPreference = 'Stop'
$vars = 'C:\Program Files\FreeSWITCH\conf\vars.xml'
$log  = 'F:\projects\oldphone-ata\repo\logs\fs-dynamic-ip.log'
function Log($m) { $line = "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') $m"; Add-Content -Path $log -Value $line -Encoding UTF8; Write-Host $line }

$text = [IO.File]::ReadAllText($vars)
if (-not (Test-Path "$vars.bak-oldphone-ip")) { Copy-Item $vars "$vars.bak-oldphone-ip" }

$text = [regex]::Replace($text, 'data="external_rtp_ip=[^"]*"', 'data="external_rtp_ip=$${local_ip_v4}"')
$text = [regex]::Replace($text, 'data="external_sip_ip=[^"]*"', 'data="external_sip_ip=$${local_ip_v4}"')
[IO.File]::WriteAllText($vars, $text, (New-Object System.Text.UTF8Encoding($false)))
Log "vars.xml updated"

Restart-Service FreeSWITCH -Force
Start-Sleep -Seconds 8
Log "service restarted"
try {
  & 'C:\Program Files\FreeSWITCH\fs_cli.exe' -x 'reloadxml' | ForEach-Object { Log "reloadxml: $_" }
  & 'C:\Program Files\FreeSWITCH\fs_cli.exe' -x 'global_getvar external_rtp_ip' | ForEach-Object { Log "external_rtp_ip=$_" }
  & 'C:\Program Files\FreeSWITCH\fs_cli.exe' -x 'sofia status' | ForEach-Object { Log "sofia: $_" }
} catch { Log "post-check failed: $_" }
Log "done"

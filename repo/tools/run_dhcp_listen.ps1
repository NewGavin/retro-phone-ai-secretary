$ErrorActionPreference = 'Continue'
$log = 'F:\projects\oldphone-ata\repo\logs\dhcp-listen.log'
Remove-Item $log -ErrorAction SilentlyContinue
# allow inbound UDP 67 so the DHCP listener can hear broadcasts
netsh advfirewall firewall delete rule name="OldPhoneDHCP" | Out-Null
netsh advfirewall firewall add rule name="OldPhoneDHCP" dir=in action=allow protocol=UDP localport=67 | Out-Null
$py = 'F:\projects\oldphone-ata\.venv\Scripts\python.exe'
$tool = 'F:\projects\oldphone-ata\repo\tools\dhcp_lease.py'
& $py $tool --listen 120 --log $log

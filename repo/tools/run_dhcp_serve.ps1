$ErrorActionPreference = 'Continue'
$log = 'F:\projects\oldphone-ata\repo\logs\dhcp-serve.log'
$py = 'F:\projects\oldphone-ata\.venv\Scripts\python.exe'
$tool = 'F:\projects\oldphone-ata\repo\tools\dhcp_lease.py'
& $py $tool --serve --mac C0-74-AD-86-AF-A0 --ip 10.13.162.60 --seconds 900 --log $log

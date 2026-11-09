$ErrorActionPreference = 'Continue'
$log = 'F:\projects\oldphone-ata\repo\logs\probe-fallback-ip.log'
Remove-Item $log -ErrorAction SilentlyContinue
function W($m) { $m | Out-File -FilePath $log -Append -Encoding utf8 }

W "=== probe start $(Get-Date -Format o) ==="
$ad = Get-NetAdapter | Where-Object { $_.Status -eq 'Up' -and $_.InterfaceDescription -like 'Realtek*' } | Select-Object -First 1
if (-not $ad) { W "no Realtek adapter up"; exit 1 }
W "adapter: $($ad.Name) idx=$($ad.ifIndex) status=$($ad.Status)"

$existing = Get-NetIPAddress -InterfaceIndex $ad.ifIndex -AddressFamily IPv4 -ErrorAction SilentlyContinue | Where-Object { $_.IPAddress -eq '192.168.1.200' }
if (-not $existing) {
    New-NetIPAddress -InterfaceIndex $ad.ifIndex -IPAddress 192.168.1.200 -PrefixLength 24 -ErrorAction Stop | Out-Null
    W "added 192.168.1.200/24"
} else { W "192.168.1.200 already present" }

Start-Sleep -Seconds 1
Get-NetIPAddress -InterfaceIndex $ad.ifIndex -AddressFamily IPv4 | ForEach-Object { W "ip: $($_.IPAddress)/$($_.PrefixLength)" }

foreach ($ip in '192.168.1.168','192.168.1.1','192.168.1.100','192.168.1.10') {
    $p = Test-Connection -ComputerName $ip -Count 2 -Quiet -ErrorAction SilentlyContinue
    W "ping $ip -> $p"
}

$open = New-Object System.Collections.ArrayList
foreach ($port in 80,443) {
    $tasks = @()
    foreach ($i in 1..254) {
        $ip = "192.168.1.$i"
        $c = New-Object System.Net.Sockets.TcpClient
        $task = $c.ConnectAsync($ip, $port)
        $tasks += [pscustomobject]@{ Ip = $ip; Port = $port; Client = $c; Task = $task }
    }
    foreach ($t in $tasks) {
        $ok = $false
        try { $ok = $t.Task.Wait(300) } catch { $ok = $false }
        if ($ok -and $t.Client.Connected) { [void]$open.Add("$($t.Ip):$($t.Port)") }
        $t.Client.Close()
    }
}
W "open tcp: $($open -join ', ')"

W "=== arp ==="
(arp -a) | Where-Object { $_ -match '192\.168\.1\.' } | ForEach-Object { W $_ }

Remove-NetIPAddress -InterfaceIndex $ad.ifIndex -IPAddress 192.168.1.200 -PrefixLength 24 -Confirm:$false -ErrorAction SilentlyContinue
W "removed 192.168.1.200"
W "=== probe done ==="

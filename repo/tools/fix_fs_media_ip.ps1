# 把 FreeSWITCH 的 external_rtp_ip / external_sip_ip 从 STUN 公网地址改成局域网 IP
# 原因：默认 vars.xml 用 stun-set 探测公网 IP（实测 121.15.12.215），
#       纯局域网场景下 SDP 会填公网地址，RTP 会发到 wan 导致「能振铃但没声音」。
# 本脚本需要管理员权限（写 C:\Program Files\FreeSWITCH\conf）。

$ErrorActionPreference = "Stop"
$conf = "C:\Program Files\FreeSWITCH\conf\vars.xml"
$log  = "F:\projects\oldphone-ata\logs\fs-media-ip.log"
$lan  = "10.13.162.128"

function Log($m) { "$(Get-Date -Format 'HH:mm:ss')  $m" | Out-File -FilePath $log -Append -Encoding utf8 }

Log "== 1/5 备份 vars.xml"
Copy-Item -LiteralPath $conf -Destination "$conf.bak-oldphone" -Force
Log "   OK  backup -> $conf.bak-oldphone"

Log "== 2/5 替换 STUN 为 $lan"
$c = Get-Content -LiteralPath $conf -Raw
$c = $c -replace '<X-PRE-PROCESS cmd="stun-set" data="external_rtp_ip=stun:stun\.freeswitch\.org"/>', "<X-PRE-PROCESS cmd=""set"" data=""external_rtp_ip=$lan""/>"
$c = $c -replace '<X-PRE-PROCESS cmd="stun-set" data="external_sip_ip=stun:stun\.freeswitch\.org"/>', "<X-PRE-PROCESS cmd=""set"" data=""external_sip_ip=$lan""/>"
[IO.File]::WriteAllText($conf, $c, (New-Object System.Text.UTF8Encoding($false)))
$verify = Select-String -LiteralPath $conf -Pattern "external_(rtp|sip)_ip" | ForEach-Object { $_.Line.Trim() }
$verify | ForEach-Object { Log "   $_" }

Log "== 3/5 重启 FreeSWITCH 服务"
Restart-Service FreeSWITCH -Force
Start-Sleep -Seconds 8
$svc = Get-Service FreeSWITCH
Log "   service $($svc.Status)"

Log "== 4/5 等待内核就绪"
$fscli = "C:\Program Files\FreeSWITCH\fs_cli.exe"
$ok = $false
for ($i = 0; $i -lt 20; $i++) {
    $out = & $fscli -x "status" 2>&1
    if ($out -match "UP 0 years") { $ok = $true; break }
    Start-Sleep -Seconds 2
}
Log "   core up: $ok"

Log "== 5/5 查看生效地址"
foreach ($v in @('external_rtp_ip','external_sip_ip')) {
    $val = & $fscli -x "eval `$`$`{$v}" 2>&1 | Select-Object -Last 1
    Log "   $v = $val"
}
& $fscli -x "sofia status" 2>&1 | Out-File -FilePath $log -Append -Encoding utf8
Log "== done"

# HT801 + 复古座机：下单要点与到货验收清单

> 软件部分（FreeSWITCH + Whisper + DSH + 回铃）已在你机器上跑通，
> 现在只差把「软电话」换成「真座机」。这份清单照着做即可。

---

## 一、买什么

| 东西 | 规格 | 合理价 | 备注 |
|---|---|---|---|
| **Grandstream HT801** | 单口 FXS ATA，5V 电源，PCMU/PCMA | 二手 **¥100–180** / 全新 ¥250–350 | 只需 1 个 FXS 口；**不要买 HT802/HT812**（双口/多口，贵且用不上）；**HT813 是 FXO**（接外线用的），也不对 |
| 备选 ATA | Linksys PAP2T / SPA112 | 二手 ¥60–150 | 也能用，但 Web UI 更老、配置项名字不同 |
| **复古座机** | 有线、4 芯听筒线、**电子铃** | ¥50–300 | 淘宝「复古仿真拨盘电话」¥120–300；闲鱼真拨盘 ¥50–150。**必须是有线**（无线/无绳的 FXS 驱动不了）；优先选「铃声是电子铃」的型号（老机械铃在 ATA 75V 下有时不响） |
| 线材 | RJ11 电话线 1 条、网线 1 条 | ¥5–15 | 座机→HT801 用 RJ11；HT801→路由器用网线 |
| 网线供电 | HT801 自带 5V 电源（二手常缺） | ¥10 | 缺电源就让卖家补，或用 5V/1A 通用电源 |

总预算：**¥300–550**（二手 ATA + 复古座机 + 线材）。
不需要：SIP 账号（本机 FreeSWITCH 自己发）、外线、运营商业务、云电话。

## 二、下单前问卖家（复制粘贴用）

闲鱼/淘宝私聊直接发：

1. 单部实价多少？打包两部能不能再便宜？
2. 含 5V 电源吗？不含的话是什么接口（5.5×2.1mm 圆口）？
3. Web 后台默认账号密码是不是 `admin/admin`？能不能恢复出厂设置？
4. 固件是原厂还是刷过？能拍一张 `Status` 页面截图吗？
5. 能不能拍一段「座机接上后，从别的分机拨这个 ATA，座机真的响铃」的短视频？
6. 外壳划痕/掉漆情况拍个近照；有没有网口松动、电源口接触不良？

> 你之前看的那家（「潮流Grandstream HT801」，7 部批量、标价单价、售出不退不换）型号是对的，
> 重点就是确认上面 2/3/5 三条，价格压到 ¥120–150 比较合理。

## 三、到货 30 分钟验收

### 1. 通电、找 IP（5 分钟）
- HT801 网线接路由器 LAN 口，座机 RJ11 接 `FXS` 口，插电。
- 有 DHCP 的网：路由器 DHCP 列表里找新设备（主机名一般 `HT8xx`），记下 IP。
- **没有 DHCP 的网（本项目实测）**：HT801 开箱默认 DHCP，拿不到地址也进不了 IVR 时，
  用电脑当「定向 DHCP」只喂它一个地址：

```powershell
# 监听谁是 Grandstream（看 MAC），然后只对它发 OFFER/ACK
..\.venv\Scripts\python.exe tools\dhcp_lease.py --listen
# 另开一个提权窗口（会加 UDP 67 入站规则 OldPhoneDHCP）
powershell -ExecutionPolicy Bypass -File tools\run_dhcp_serve.ps1 -Mac "C0-74-AD-86-AF-A0" -Ip "10.13.162.60" -Seconds 900
```

- 拿到 IP 后浏览器打开 `http://<IP>`，账号 `admin` / 密码 `admin`。进不去 → 长按背后 RESET 约 10 秒恢复出厂再试
  （二手设备后台密码常被前主人改过；本项目实测重置后 `admin/admin` 可用）。

### 2. 配 SIP（10 分钟）

可以直接用脚本配（推荐，实测值就是下面这套）：

```powershell
..\.venv\Scripts\python.exe tools\ht801_cfg.py login --ip 10.13.162.60
..\.venv\Scripts\python.exe tools\ht801_cfg.py set-ip   --ip 10.13.162.60 --static 10.13.162.60 --mask 255.255.254.0 --gateway 10.13.163.254 --dns 223.5.5.5
..\.venv\Scripts\python.exe tools\ht801_cfg.py set-fxs  --ip 10.13.162.60 --server 10.13.162.128 --user 100 --auth 100 --password phone1234 --name 座机 --auto-dial 6001
..\.venv\Scripts\python.exe tools\ht801_cfg.py reboot   --ip 10.13.162.60
```

手工在 Web UI 填的话，对应位置：

| 位置 | 值 |
|---|---|
| Basic Settings → IP 模式 | `Statically configured` + 静态 IP/掩码/网关/DNS（本项目：`10.13.162.60 / 255.255.254.0 / 10.13.163.254 / 223.5.5.5`） |
| FXS Port → Primary SIP Server | `<本机内网 IP>:5060`（电脑上 `ipconfig` 查，当前是 `10.13.162.128`；IP 变了要同步改 ATA 与 `vars.xml`） |
| SIP User ID | `100` |
| Authenticate ID | `100` |
| Authenticate Password | `phone1234` |
| Name | `座机` |
| **FXS Port → Offhook Auto-Dial** | `6001` ← 一拿起话筒自动呼叫电脑 |
| Preferred Vocoder | 只留 `PCMU`（顺序 1，`P57=0`） |
| Use STUN | No / 关 |
| NAT Traversal | 保持默认（局域网不用开） |

点 `Save and Apply`（脚本等价于 `POST /cgi-bin/update` + `/cgi-bin/rs` 重启），回 `Status` 页看 **SIP Registration: Registered**。

> 电脑端确认：`"C:\Program Files\FreeSWITCH\fs_cli.exe" -x "sofia status profile internal reg"`
> 应多出一条 `User: 100@10.13.162.128`（IP 跟着电脑走）、
> `Contact: <sip:100@10.13.162.60:5060>`、`Agent: Grandstream HT801 1.0.33.4`。

### 3. 三连测试（15 分钟）

```powershell
# ① 振铃：电脑主动拨座机（拿起话筒应听到这句测试语音）
cd F:\projects\oldphone-ata\repo
..\.venv\Scripts\python.exe oldphone.py reply --text "座机接入测试，听到这句话说明振铃和语音都通了。"

# ② 上行：拿起话筒（自动拨 6001）说一句「老座机，帮我看看当前目录有什么文件」，然后挂机。
#    等 10~20 秒看日志，再等座机回铃（接起来听 DSH 的答复）
Get-Content .\logs\watch.log -Tail 5

# ③ 全链路：什么都不用做，① ② 通过即可。
```

**验收判据**：
- ① 座机响铃 + 接起来听到测试语音 → 下行 OK
- ② 挂机后 `C:\fs\recordings` 出现新 wav，`watch.log` 显示「发现新录音」→ 上行 OK
- ② 的回铃响起、接起来听到 DSH 答复 → **完整闭环 OK**

## 四、可能踩的坑（对照排查）

| 现象 | 处理 |
|---|---|
| 注册不上 `Registered` 一直红 | 先 `ipconfig` 确认电脑当前 IP（DHCP 可能已变，本机 2026-11-04 是 `192.168.124.26`），HT801 的 SIP Server 必须写这个 IP 而不是 localhost/旧 IP；再查密码 `phone1234`、是否同一网段 |
| 能拨通但没声音 | HT801 关掉 STUN；`fs_cli -x "global_getvar external_rtp_ip"` 应等于当前电脑 IP（vars.xml 已配成 `$${local_ip_v4}` 自动跟随） |
| 拿起话筒不自动拨 | `Offhook Auto-Dial` 没填或没保存；确认填的是 `6001` |
| 座机不响铃 | 老机械铃对 75V 不敏感 → 换电子铃座机；或 ATA 的 `Ring Voltage` 调高 |
| 录音是杂音/很小 | 复古座机碳精麦老化 → 换驻极体话筒（¥1-3）或直接换台座机；先确认 `Offhook Auto-Dial` 通的是 FreeSWITCH 而不是拨号音 |
| 挂机后座机还占线 | FreeSWITCH 没收到挂机信号；看 `fs_cli -x "show channels"`，必要时重启 ATA |

## 五、装好之后要改的唯一一处配置

不用改代码。HT801 里填的 SIP Server 就是电脑内网 IP；FreeSWITCH 侧分机 100 和 6001 都已配好，
`vars.xml` 的 `external_rtp_ip/external_sip_ip` 已改成跟随本机 IP（`$${local_ip_v4}`），IP 变了
FreeSWITCH 自己会跟。**只有 ATA（和软电话）里的 SIP Server 需要手动改**：电脑换了内网 IP
（比如重连 Wi-Fi / 重启路由器）就 `ipconfig` 查新 IP 填进去。
建议在路由器里给电脑和 HT801 都做 **DHCP 静态保留**，一劳永逸。

---

**买回来卡住了就把 HT801 的 Status 页截图发我，我帮你看。**

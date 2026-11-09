# 复古座机 × AI 秘书（Retro Phone AI Secretary）

把一台老式拨号/按键座机接到 Windows 上，**当麦克风用**：拿起话筒说一句话，本地转写成文字交给 AI；
AI 干完活，**座机真的响铃**，接起来听它汇报结果。

> 不是"把 TTS 放到座机喇叭里"的玩具——这里走的是 ATA + FreeSWITCH + SIP，
> 振铃电压、摘挂机检测、双向音频都是真的电话链路。全程局域网，不接 PSTN、无月租、不产生话费。

---

## 效果（实测记录，2026-11）

```
拿起话筒（自动拨 6001）→ 说「帮我看一下当前目录有什么文件」→ 挂机
        ↓ 约 13 秒（本地 Whisper medium，CPU）
文字进入本机 AI 会话 → AI 真的执行 `ls` → 回答
        ↓ watcher 解析会话日志，取最后一段回答 → 压成 260 字口语摘要 → TTS（8kHz）
座机响铃 → 接起来听到：「当前目录里有 freeswitch、hooks、logs……其中没有 Vimeo 文件。」*
```

\* ASR 把 README 听成了 Vimeo——这是 8kHz 窄带电话音的典型误识别，见[已知限制](#已知限制)。

真机链路：`Grandstream HT801 1.0.33.4` 注册成功（`Status: Registered(UDP)`、`Ping-Status: Reachable`），
回铃日志 `Callstate Change RINGING -> ACTIVE` → `CS_CONSUME_MEDIA -> CS_EXECUTE`。

## 为什么会有这个项目

网上流传过一个"老座机接电脑、AI 干完活回拨"的项目。实际扒下来发现：
所谓"异步回拨"只是把 TTS 音频播放到座机喇叭（`notifier.py` 里一行 `play_pcm_async`），
没有拨号、没有振铃、没有 SIP；摘挂机还是靠麦克风 RMS 猜的。

我们做了一个真的版本：

| 环节 | 原项目 | 本仓库 |
|---|---|---|
| 拾音 | 声卡直连老式碳精麦（电流不足，不可行） | ATA 48V 馈电，原装话筒直接可用 |
| 摘挂机 | 麦克风 RMS > 阈值猜 | 叉簧信号由 ATA 硬件检测（拨号即摘机） |
| 回铃 | TTS 放音到喇叭 | **真 SIP 呼叫 → 真振铃** |
| Agent 完成通知 | 无（角色扮演叙述） | 会话日志解析 / Codex notify / DSH 插件 |

## 架构

```
┌──────────────┐  RJ11   ┌──────────┐  网线   ┌──────────────┐
│ 复古座机      │────────▶│ HT801 ATA │────────▶│   路由器/局域网 │
│（电子铃座机）  │◀────────│ (FXS)     │◀────────│              │
└──────────────┘         └──────────┘         └──────┬───────┘
                                                      │ SIP / RTP
                                              ┌───────▼────────┐
                                              │  Windows 电脑   │
                                              │                │
                                              │ FreeSWITCH     │  6001 → 接听 → 录音
                                              │  (分机 100)     │
                                              │      │          │
                                              │      ▼          │
                                              │ watcher（计划任务，轮询录音目录）
                                              │      │          │
                                              │      ├─ faster-whisper（本地 ASR）
                                              │      ├─ 注入 AI 会话（DSH / Codex / 任意 CLI）
                                              │      └─ edge-tts → 8kHz wav → 回拨
                                              └────────────────┘
```

## 硬件清单

| 件 | 说明 | 参考价（2026-11，二手/全新浮动） |
|---|---|---|
| Grandstream HT801 | 单口 FXS ATA，1 个 SIP 账号即可 | 二手 ¥100–180 / 全新 ¥250–350 |
| 复古座机 | **优先电子铃**（机械铃对振铃功率要求高），按键式或拨盘式都行 | ¥50–300 |
| 网线、5V 电源 | HT801 自带 | ¥10 |
| （可选）软电话 MicroSIP | 硬件到货前先验收软件链路 | 免费 |

合计约 **¥300–550**。备选 ATA：Linksys PAP2T / SPA112（二手 ¥60–150）。
**不要买** HT802/HT812/HT813（双口/带 FXO，用不上还更贵）。

## 软件栈

- Windows 10/11
- [FreeSWITCH](https://freeswitch.org/) 1.11.x（Windows 官方 MSI）
- Python 3.11：`edge-tts`（TTS）、`faster-whisper`（本地 ASR，medium int8）、`PyYAML`、`zstandard`（解析 DSH 会话日志）
- ffmpeg（TTS 转 8kHz 单声道）
- 可选：[DSH](https://github.com/deepseek-ai) 桌面版 + `dsh-idle-watchdog` 插件（把电话指令注入正在用的 GUI 会话）
- 可选：Codex CLI（`notify` 钩子）/ Claude Code（Stop hook）

## 目录结构

```
oldphone-ata/
├─ repo/                     # 业务代码（npm 风格无所谓，纯 Python）
│  ├─ oldphone.py            # 主程序：转写 / 派活 / 回铃 / 路由
│  ├─ config.yaml            # 全部配置
│  ├─ requirements.txt
│  ├─ freeswitch/            # 分机与拨号计划 XML（拷进 FreeSWITCH 的 conf）
│  ├─ hooks/codex_notify.py  # Codex 任务完成 → 回铃钩子
│  ├─ docs/hardware-checklist.md
│  ├─ README.md              # 运维手册（安装/排错细节都在这）
│  └─ tools/                 # watcher、体检、HT801 配置、DHCP 辅助…
├─ .gitignore
└─ DEBUG-REPORT-2026-11-04.md  # 一晚踩坑实录（DSH 沙箱/temp 规则等）
```

> `repo/tools/softphone/`、`.venv/`、`.cache/` 等运行环境不进版本库。

## 快速开始

> 完整步骤与排错见 [repo/README.md](repo/README.md)。这里只列主干。

### 1. FreeSWITCH

```powershell
# 装好 FreeSWITCH 1.11.x（Windows MSI），建议目录 C:\FreeSWITCH
# 拷分机与拨号计划（脚本会自动备份并 reloadxml）
powershell -ExecutionPolicy Bypass -File repo\tools\setup_freeswitch.ps1
```

要点：
- 分机 `100` / 密码 `phone1234`，用独立 context `oldphone`（避开系统 `valet_park` 对 6000–6099 的占用）
- `6001`：接听 → 录音到 `C:\fs\recordings`
- `conf\vars.xml` 里 `external_rtp_ip` / `external_sip_ip` 必须指向本机内网 IP，否则「能振铃没声音」

### 2. Python 依赖

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r repo\requirements.txt
```

### 3. 配 ATA（HT801）

有 DHCP 的网：登录 `http://<ata-ip>`（`admin/admin`），配 SIP：
Server = `<电脑内网 IP>:5060`、User/Auth = `100`、Password = `phone1234`，
FXS 口 **Offhook Auto-Dial = 6001**，编解码只留 PCMU，关 STUN。

**没有 DHCP 的网**（本项目遇到的情况）：用仓库里的定向 DHCP 先给它发个地址，再改成静态：

```powershell
.\.venv\Scripts\python.exe repo\tools\dhcp_lease.py --listen     # 找出 ATA 的 MAC
# 提权另开窗口（会加 UDP 67 入站规则）
powershell -ExecutionPolicy Bypass -File repo\tools\run_dhcp_serve.ps1 -Mac "C0-74-AD-86-AF-A0" -Ip "10.13.162.60" -Seconds 900
# 拿到地址后直接脚本配好静态 IP + SIP
.\.venv\Scripts\python.exe repo\tools\ht801_cfg.py login  --ip 10.13.162.60
.\.venv\Scripts\python.exe repo\tools\ht801_cfg.py set-ip --ip 10.13.162.60 --static 10.13.162.60 --mask 255.255.254.0 --gateway 10.13.163.254 --dns 223.5.5.5
.\.venv\Scripts\python.exe repo\tools\ht801_cfg.py set-fxs --ip 10.13.162.60 --server <电脑内网IP> --user 100 --auth 100 --password phone1234 --name 座机 --auto-dial 6001
```

### 4. 注册 watcher（关键：不要用挂机钩子）

```powershell
powershell -ExecutionPolicy Bypass -File repo\tools\register_watcher_task.ps1
```

它注册一个「登录时以用户令牌运行」的计划任务 `OldPhoneWatcher`，常驻轮询录音目录。
**必须用用户令牌**：FreeSWITCH 的 `api_hangup_hook` 以 SYSTEM 身份执行，
既会卡挂机线程 12 秒，又让 DSH 沙箱（需要登录 SID）起不来。

### 5. 自检

```powershell
.\.venv\Scripts\python.exe repo\oldphone.py selftest     # TTS→8k→ASR 回读
.\.venv\Scripts\python.exe repo\tools\doctor.py          # 一键体检
.\.venv\Scripts\python.exe repo\oldphone.py reply --text "这是一次回铃测试"
```

## 电话里怎么用

1. 拿起话筒 → HT801 自动拨 `6001` → 听到"咔"一声（无回铃音，直接开始说话）
2. 说完直接挂机
3. 20 秒 ~ 2 分钟后座机响铃，接起来听摘要，详细内容留在 AI 会话里

### 让 AI 把指令"插到"指定会话

电话里描述目标会话（"这条插到聊 PPT 数据传输的那个会话"），AI 会用 `route` 转发：

```powershell
.\.venv\Scripts\python.exe repo\oldphone.py chats --limit 20
.\.venv\Scripts\python.exe repo\oldphone.py route --chat "月度考核汇总工作讨论" --text "看一下九月份各年级的表有没有改动"
```

- 支持会话 id、≥6 位唯一前缀、标题
- 不指定 → 自动落"最近活跃"的会话（按会话日志最后写入时间，不是创建时间）
- 回电内容跟着**目标会话**的回答走

## 配置要点（`repo/config.yaml`）

| 键 | 说明 |
|---|---|
| `agent.mode` | `bridge`（注入桌面 GUI 会话）/ `dsh`（另起 headless）/ `echo`（只回声，调试用） |
| `bridge.chat` | `auto` = 最近活跃会话；也可写死 id/标题 |
| `bridge.secret_file` | `dsh-idle-watchdog` 的 API secret（等同该会话 shell 权限，注意保管） |
| `asr.model` | `medium` 准但慢（约 2× 实时），`small` 快但中文易错 |
| `pbx.ring_timeout` | 回铃等待秒数 |
| `agent.phone_reply_chars` | 电话里念的摘要上限（默认 260 字） |

## 已知限制

- **ASR 错字**：8kHz 窄带 + 中文场景词，偶尔把 README 听成 Vimeo；可用 `initial_prompt` 提示词缓解
- **时延**：6 秒录音约 13 秒转写（CPU medium 含模型加载）；想快可换 `small` 或 GPU
- **IP 变化**：想换网段要同步 `vars.xml`、ATA 的 SIP Server、防火墙规则
- **DSH 沙箱**：headless 模式下 `temp` 必须在 workspace **之外**且可写，否则命令跑不了（见 `DEBUG-REPORT`）
- **振铃功率**：机械铃座机可能带不动，优先电子铃

## 安全与合规

- **只连局域网**，不要把 FXS 口接公共电话网（PSTN），也不要做外呼营销
- `dsh-idle-watchdog` 的 secret 等于"能以你的身份给会话发指令"，只监听 loopback，勿暴露公网
- 录音文件默认落在 `C:\fs\recordings`，按需自行清理
- 个人自用场景；涉及他人录音请遵守当地法律

## 相关项目与致谢

- [Grandstream HT801](https://www.grandstream.com/)：单口 FXS ATA
- [FreeSWITCH](https://freeswitch.org/)：真振铃与录音
- [faster-whisper](https://github.com/SYSTRAN/faster-whisper)：本地 ASR
- [edge-tts](https://github.com/rany2/edge-tts)：免费 TTS
- [dsh-idle-watchdog](https://github.com/lucagiftzek/DSH-Idle-Watchdog)：向运行中的 DSH 会话注入消息
- [JFC MicroSIP](https://github.com/JFC-Group/JFC-microsip)：硬件到货前的软电话

## License

MIT

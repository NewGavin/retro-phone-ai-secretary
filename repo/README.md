# 老座机 AI 秘书（ATA + FreeSWITCH）

把一台复古座机变成电脑的「语音输入 + 任务完成回铃」终端：
**拿起话筒说话 → 本地转写 → 交给本机 DSH（或 Codex/Claude）→ 任务完成后座机真振铃，接起来听结果。**

全程局域网，不接运营商、无月租、无号码。

```
复古座机 ──RJ11──▶ HT801(ATA) ──网线──▶ 路由器 ──▶ Windows
                                                  ├─ FreeSWITCH（PBX：接听/录音/振铃）
                                                  └─ 本项目（Whisper 转写 → Agent → edge-tts）
```

---

## 0. 目录结构（2026-11-04 重构：代码在 `repo/`，运行环境在容器根）

DSH 的 Windows 沙箱有一条硬规则：**临时目录必须在 workspace 之外，且当前进程真的能写**。
所以把「agent 的工作区」= `repo/`，临时目录 = 容器根的 `.tmp/`，两者是兄弟关系：

```
F:\projects\oldphone-ata\        ← 容器根（不放业务代码）
├─ .venv\                           # Python 3.11 虚拟环境（所有脚本共用）
├─ .tmp\                            # DSH 沙箱的临时目录（必须在 workspace 之外）
├─ .dsh-home\                       # DSH headless 的私有家目录
├─ .cache\                          # HuggingFace 模型缓存（Whisper）
├─ tools\softphone\                 # MicroSIP 便携版（无硬件联调用的软电话）
└─ repo\                            ← agent 的 workspace，也是本项目的代码根
   ├─ oldphone.py                   # 主程序（TTS / ASR / 回铃 / 完整链路）
   ├─ config.yaml                   # 配置：fs_cli、分机号、agent、DSH、ASR
   ├─ requirements.txt
   ├─ freeswitch\
   │  ├─ 100.xml                    # → conf/directory/default/100.xml（user_context=oldphone）
   │  └─ oldphone.xml               # → conf/dialplan/oldphone.xml（context oldphone，扩展 6001）
   ├─ hooks\codex_notify.py         # Codex 回合结束钩子（可选玩法）
   ├─ tools\
   │  ├─ watch_recordings.py        # 常驻 watcher：盯录音目录，发现新文件就起 listen-worker
   │  ├─ register_watcher_task.ps1  # 注册/启动 OldPhoneWatcher 计划任务（登录自启）
   │  ├─ doctor.py                  # 一键体检（FS / 分机 / 拨号计划 / fs_cli / 回铃命令）
   │  ├─ deploy_dialplan.ps1        # 把 repo/freeswitch/*.xml 拷进 FreeSWITCH 并 reloadxml
   │  ├─ dsh.py                     # 单独测试 DSH（等价于 oldphone.py ask）
   │  └─ bench_asr.py               # ASR 模型速度/准确率对比
   ├─ logs\  outbox\  tasks\  tts\  # 运行产物
```

> 为什么不能把代码直接放容器根：workspace 若是容器根，`.tmp` 就在 workspace 内部，
> DSH 会直接报 `Windows ACL temp root must be outside the workspace`。

## 1. 安装

```powershell
cd F:\projects\oldphone-ata
py -3.11 -m venv .venv          # 或直接复用已建好的 .venv
.\.venv\Scripts\python.exe -m pip install -r repo\requirements.txt `
    -i https://pypi.tuna.tsinghua.edu.cn/simple
```

FreeSWITCH：官网下载 **Windows MSI**（已验证 1.11.3 可下载，168 MB）：
<https://files.freeswitch.org/windows/installer/x64/FreeSWITCH-1.11.3-Release-x64.msi>

安装建议自定义目录 **`C:\FreeSWITCH`**（不要带空格、不要中文），管理员运行安装包，
安装类型选 Custom，保留默认组件（**别取消 Sound files**），勾选安装为服务。
本项目会自动按 `config.yaml → C:\FreeSWITCH → C:\Program Files\FreeSWITCH → PATH` 找 `fs_cli.exe`。

## 2. 先跑无硬件自检（现在就能做）

```powershell
cd F:\projects\oldphone-ata\repo
..\.venv\Scripts\python.exe oldphone.py selftest
```

它会：edge-tts 合成一句中文 → ffmpeg 转 8kHz 单声道 wav → faster-whisper 回读。
看到「✅ 链路通」说明 TTS、音频转换、ASR 全部就绪（首次会下载 medium 模型约 1.5GB，走 hf-mirror）。

**本机实测（2026-11，CPU int8）**：6.6s 音频，small 识别 2.9-3.0s（0.45x 实时）但会听错
「老座机链路自检」；medium 识别 7.8-8.4s（约 1.2x 实时）全对。默认用 medium。
要更低延迟就换 `model: "small"`，或把 `asr.engine` 接到火山云 ASR（流式、按小时计费）。

也可以单独试：

```powershell
..\.venv\Scripts\python.exe oldphone.py tts --text "任务完成，代码已通过测试" -o tts\demo.wav
..\.venv\Scripts\python.exe oldphone.py asr --wav C:\fs\recordings\xxx.wav
```

## 3. FreeSWITCH 配置（装完照着做，5 分钟）

装完 FreeSWITCH 后，**管理员** PowerShell 里执行（脚本已写成纯 ASCII，可直接跑）：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File F:\projects\oldphone-ata\repo\tools\setup_freeswitch.ps1
```

它做 5 件事：拷 `100.xml` 和 `oldphone.xml` 到 FreeSWITCH 的 conf → 建 `C:\fs\recordings`
并放开权限 → 防火墙放行 UDP 5060 与 16384-32768 → 服务设为自动并启动 → `reloadxml` 验证。

> 本机已装好：`C:\Program Files\FreeSWITCH`，服务名 `FreeSWITCH`，
> 分机 100 的 domain 跟随本机内网 IP（**当前是 `192.168.124.26`**，用 `ipconfig` 查，
> 不是 localhost），internal profile 监听 `<本机IP>:5060`。HT801/软电话都填这个 IP。
> ⚠️ 家里是 DHCP，IP 变了要同步改 ATA/软电话里的 SIP Server（见下面第 1 条）。

另外两处已改过、重装系统时要重做的事：

1. `conf\vars.xml` 里 `external_rtp_ip` / `external_sip_ip` 默认用 STUN 探公网 IP，
   纯局域网时 SDP 会填公网地址 → 能振铃没声音。已改成**跟随本机 IP** 的
   `$${local_ip_v4}`（脚本：`repo\tools\fix_fs_dynamic_ip2.ps1`，备份
   `vars.xml.bak-oldphone-ip` / `vars.xml.bak-oldphone-ip2`）。
   注意：PowerShell 改这个文件时 `$$` 会被正则/替换吃掉，必须用 `String.Replace`
   或写 `$$$$`；写错成 `${local_ip_v4}` 会导致 IPv4 profile 起不来、5060 不监听。
2. 6001 落在系统默认拨号计划的 `valet_park` 正则 `^((?!6000)60\d{2})$`（吃掉 6000-6099），
   所以分机 100 必须用**独立 context** `oldphone`（`100.xml` 里的 `user_context`），
   拨号计划文件也从 `conf/dialplan/default/` 挪到 `conf/dialplan/oldphone.xml`。

体检（一次看清哪环没通）：

```powershell
F:\projects\oldphone-ata\.venv\Scripts\python.exe F:\projects\oldphone-ata\repo\tools\doctor.py --full
```

期望：Python / ffmpeg / 录音目录 / fs_cli / 内核 / SIP / 分机 100 / 拨号计划 6001 / 本机 IP 全 ✅，
`--full` 再加一次 TTS→8k→ASR 回读。

## 4. HT801 配置（座机接入）

Web UI 默认地址看路由器 DHCP 列表，账号 `admin/admin`（二手可能被改过，需要恢复出厂）。

| 页面 | 配置 |
|---|---|
| Profile 1 → SIP Server | `<本机内网 IP>:5060`（当前 `192.168.124.26`，用 `ipconfig` 查） |
| SIP User ID / Auth ID | `100` / `100` |
| Password | `phone1234`（与 `freeswitch/100.xml` 一致） |
| **FXS Port → Offhook Auto-Dial** | `6001` ← **关键：一拿起话筒就自动呼叫电脑** |
| 编码 | 只留 PCMU/PCMA，ptime 20ms |
| 网络 | 关掉 STUN / 关闭路由自动获取，固定 IP 或 DHCP 保留 |

## 5. 联调顺序（别跳步）

1. **软电话验证振铃**：`F:\projects\oldphone-ata\tools\softphone\microsip.exe`
   （JFC MicroSIP 3.21.4 便携版）已备好，注册分机 `100`（SIP Server/Domain 用本机内网 IP，当前 `192.168.124.26`、Login `100`、
   密码 `phone1234`、Media Encryption 关）。
2. **验证录音**：用软电话拨 `6001`，说一句话后挂断 → `C:\fs\recordings` 出现 wav。
3. **验证回铃**：`python oldphone.py reply --text "测试回铃"` → 软电话/座机振铃，接听听到语音。
4. **验证完整链路**：`python oldphone.py listen --wav <录音>`（或把 wav 丢进录音目录让 watcher 捡到）。

## 6. 运行架构（重点：为什么用 watcher 而不是挂机钩子）

```
座机拨 6001 → FreeSWITCH（context oldphone）接听并录音 → 挂机
                                                        │
                            C:\fs\recordings\*.wav  ◀──┘
                                     │
                    OldPhoneWatcher（登录自启的计划任务，普通用户令牌）
                                     │ 发现新 wav（1.5s + 大小稳定）
                                     ▼
                    listen-worker：Whisper 转写 → DSH 跑任务（后台）→ edge-tts → 回铃
```

早期版本用 FreeSWITCH 的 `api_hangup_hook=system ...`，有两个坑，已全部弃用：

1. **同步阻塞**：钩子会卡住挂机线程 12 秒（Whisper 加载期间通道一直不能 DESTROY）。
2. **SYSTEM 身份跑 DSH，沙箱起不来**：DSH 报「缺少登录 SID / 只能读文件、跑不了命令」，
   等于电话派下去的活干不了。

改成 watcher 后：挂机瞬间释放通道，watcher 用**用户自己的令牌**起后续流程，DSH 的工具权限正常。

### 6.1 DSH 沙箱的两个硬性条件（踩了一晚上才定位）

- **临时目录必须在 workspace 之外**：`workspace = ...\repo`，`temp = ...\.tmp`（兄弟目录）。
  放 workspace 内直接报 `Windows ACL temp root must be outside the workspace`。
- **临时目录必须真的可写**：默认 `%TEMP%` 在很多启动方式下写不进（计划任务/降权令牌），
  会报 `temp grant materialization failed` 或锁文件 `Permission denied`，
  表现就是「agent 能聊天但跑不了命令」。
  本项目在 `config.yaml` 里固定：

```yaml
agent:
  mode: dsh
  async: true              # 先挂断，后台跑完再主动回拨
  phone_reply_chars: 260   # 电话里最多念多少字（长答复会压成口语，完整版进 outbox）
  dsh:
    exe: "D:/DSH/DeepSeek Harness.exe"
    cli: "D:/DSH/resources/app.asar/dsh/node_modules/@deepseek-ai/dsh/lib/bin.js"
    profile: "headless"
    home: "F:/projects/oldphone-ata/.dsh-home"        # 私有 DSH_HOME，避免和桌面版抢 cordis.yml
    credentials: "C:/Users/Gavin/.dsh/.credentials.yaml" # key 从 refs.DEEPSEEK_API_KEY 读
    key_ref: "DEEPSEEK_API_KEY"
    timeout: 1800
    temp: "F:/projects/oldphone-ata/.tmp"             # DSH 沙箱临时目录（必须在 repo 之外）
```

### 6.2 watcher 的部署/开机自启

```powershell
# 注册（并立刻启动）OldPhoneWatcher：登录时以交互令牌运行 pythonw repo\tools\watch_recordings.py
powershell -NoProfile -ExecutionPolicy Bypass -File F:\projects\oldphone-ata\repo\tools\register_watcher_task.ps1
```

- 任务名 `OldPhoneWatcher`，登录触发（`TASK_TRIGGER_LOGON`），LogonType=3（交互令牌），不提升。
- 单实例靠 `repo\logs\.watch.lock`（msvcrt 文件锁）；日志 `repo\logs\watch.log`。
- 手工停/起：`Stop-ScheduledTask -TaskName OldPhoneWatcher` / `Start-ScheduledTask -TaskName OldPhoneWatcher`。

## 7. 接 Agent：本机 DSH 直接可用（推荐）

本机没装 Codex/Claude CLI，但 DSH 桌面版自带一套 **headless CLI**（打包在 `app.asar` 里），
可以一次性跑完一个任务并把结果打印到 stdout，正好当「电话那头的 AI」用。

原理：Electron 支持 `ELECTRON_RUN_AS_NODE=1` 以纯 Node 模式运行，于是可以直接执行
`app.asar` 内的 `@deepseek-ai/dsh/lib/bin.js`；API key 从 DSH 自己的凭据文件
`~/.dsh/.credentials.yaml` 的 `refs.DEEPSEEK_API_KEY` 读取。

验证：

```bat
cd F:\projects\oldphone-ata\repo
..\.venv\Scripts\python.exe oldphone.py ask --text "用命令看一下当前目录有哪些文件，一句话总结"
..\.venv\Scripts\python.exe oldphone.py listen --wav tts\selftest.wav
```

`async: true` 时：`listen` 转写完就退出，后台子进程跑 `dsh-task`，
完成后把答复写到 `outbox/reply-*.txt`、合成 8k wav 再回拨；
日志 `repo\logs\dsh-*.log`，任务原文 `repo\tasks\prompt-*.txt`。

想换成别的 CLI 就把 `mode` 改回 `command`，写 `command: 'codex exec ... "{prompt}"'`。

### 7.1 bridge 模式：电话指令投进「当前桌面 DSH 会话」（最新，推荐）

`mode: dsh` 是另起一个 headless 会话来干活，和 GUI 里这间会话是两段上下文。
如果想让「电话里说的话，直接出现在你现在用的这间 DSH 会话里」，就用 `bridge` 模式：
通过插件 **dsh-idle-watchdog** 的 HTTP 接口，把 ASR 文本作为一条**用户消息**投进指定会话。

流程：

1. 录制 → watcher → ASR（同前）
2. `dispatch()` 走 bridge：`POST http://127.0.0.1:<DSH端口>/dsh-idle-watchdog/api/prompt`
   body `{chat, message, provenance}`，鉴权头 `x-idle-watchdog-secret`
3. 桌面会话收到一条「【座机来电】…」用户消息，agent 用**完整上下文**处理并回答
4. **确定性回电**：watcher 轮询这间会话的 `session.v4.jsonl.zstd`，发现这条「【座机来电】」
   并走完一轮后，自动取最后一段回答 → 压成口语摘要 → TTS → 回拨座机
5. 座机振铃，接起来听总结（不依赖 agent 执行命令，agent 回答完即可）

配置（`config.yaml`）：

```yaml
agent:
  mode: bridge
bridge:
  url: "auto"        # 自动探测桌面端端口（桌面端每次重启都会换端口）
  chat: "auto"       # auto = 最近活跃的会话；也可写死 session id / ≥6 位前缀 / 标题
  cwd: ""            # 留空 = 不按目录过滤；想让电话固定落在某个项目时可填 cwd
  secret_file: "C:/Users/Gavin/.dsh/idle-watchdog/api-secret"
  timeout: 60        # 会话正忙时插件会排队，等它接收要几十秒
  sessions_dir: "C:/Users/Gavin/.dsh/sessions"   # 确定性回电要解析会话日志
  callback_ttl_seconds: 900                      # 等回电的最长时间，超时就不回拨
```

`chat: auto` 的「最新活跃」是按会话日志 `session.v4.jsonl.zstd` 的最后写入时间算，
不是创建时间 —— 最近真的在用哪间，电话就落哪间。

前置条件：桌面端插件市场装好并启用 `dsh-idle-watchdog`，secret 文件存在（权限 0600）；
插件路由是启动时挂载的，装/升级插件后要重启一次 DSH 桌面端。

自检：

```bat
cd F:\projects\oldphone-ata\repo
..\.venv\Scripts\python.exe tools\_bridge_probe.py
```

`bridge` 模式下 `oldphone.py listen --wav xxx.wav` 只做「转写 + 投递」，不会自己回电；
回电由 watcher 的 `check_phone_callback()` 完成：待回电记录写在 `.tmp/phone-pending.json`
（默认 900 秒内有效），它解析会话日志里这一轮的回答 → 摘要 → TTS → 回拨座机。
自检：`tools/_callback_unit.py`（假会话日志验证解析与触发）、
`tools/_callback_probe.py`（看真实会话里有没有【座机来电】消息）。

### 7.2 电话指令路由：口述目标会话，自动分派

不想被钉死在一间会话里时：在电话里**用一句话描述要插到哪间会话**，例如
「这条插到那个聊 PPT 数据传输的会话里」，agent 会用 `route` 子命令转发到目标会话，
处理完由 watcher 自动回电（回电内容跟着**目标会话**的回答走）。

```bat
cd F:\projects\oldphone-ata\repo
:: 1) 看有哪些会话可选（id / 标题 / 目录 / 是否 live）
..\.venv\Scripts\python.exe oldphone.py chats --limit 20

:: 2) 转发一条电话原话到指定会话（id、≥6 位唯一前缀、或标题都可以）
..\.venv\Scripts\python.exe oldphone.py route --chat "IM插件无法启用排查" --text "把刚才那个插件报错再看一眼"
```

规则：

- 电话里**没说**要哪间 → 自动落「最近活跃」会话（`bridge.chat: auto`）。
- 电话里**说了**要哪间 → agent 依据 `chats` 的标题/目录匹配，用 `route` 转发；匹配不到就留在本会话并问你。
- `route` 会把原话包装成同样的「【座机来电】…」消息，并在目标会话里以 user 身份出现；
  同时写入 `phone-pending.json`，确保回电内容取自**目标会话**的这一轮回答。
- 汇报保持简短：目标会话照常详答，回电只念口语摘要（`agent.phone_reply_chars`，默认 260 字）。

## 8. 排错

| 现象 | 原因 / 处理 |
|---|---|
| `fs_cli` 找不到 | 改 `config.yaml` 的 `pbx.fs_cli` 为实际安装路径 |
| 座机不响 | ① ATA 未注册（`fs_cli -x "sofia status"`）② 振铃电压不够，换电子铃座机 ③ 防火墙挡了 RTP |
| 能振铃但没声音 | `vars.xml` 的 external_rtp_ip 被 STUN 探成公网，SDP 地址错；改成本机内网 IP |
| 拨 6001 没录到音 | 6001 被 default context 的 `valet_park` 抢走；确认分机 100 的 `user_context=oldphone` 且 `conf/dialplan/oldphone.xml` 已加载 |
| 挂机后脚本没跑 | 本项目已改用 watcher，不用 `api_hangup_hook`；确认 `Get-ScheduledTask OldPhoneWatcher` 在跑、`repo\logs\watch.log` 有记录 |
| agent 能回答但「跑不了命令」 | DSH 沙箱 temp 不可写：确认 `agent.dsh.temp` 存在且可写，且不在 `repo\` 内部 |
| `Windows ACL temp root must be outside the workspace` | temp 指进了 workspace；改成容器根的 `.tmp` |
| `EPERM ... cordis.yml` | 桌面版与 CLI 抢 profile 文件。确认 `agent.dsh.home` 指向 `.dsh-home`；仍报错就删掉 `.dsh-home` 让它重建 |
| `dsh: MISSING_CREDENTIAL` | `~/.dsh/.credentials.yaml` 里没有 key：在 DSH 桌面版「模型设置」填一次 |
| ASR 乱码/为空 | 8kHz 窄带；靠近话筒说、加 `vad_filter`，或换 `model: medium` |
| 回铃 45 秒没人接就断 | `config.yaml` 的 `pbx.ring_timeout` 控制，可以加大或后面加自动重呼 |
| 投递 404 / 找不到 `dsh-idle-watchdog` | 插件没启用，或桌面端刚重启还没挂载：请求 `/dsh-idle-watchdog/api/health` 应返回 200 |
| 投递超时 | 目标会话正在跑，插件会排队等空闲；把 `bridge.timeout` 加到 60，或错峰再试 |
| 投递 401 | secret 不一致：`~/.dsh/idle-watchdog/api-secret` 要和插件里保存的一致（文件缺失就重新生成） |
| 投错会话 | `bridge.cwd` 没匹配或留空；填目标会话的 cwd，或把 `bridge.chat` 写成会话 id |

## 9. 合规与安全

- 本方案**不接公共电话网**，ATA 的 FXS 口只接自己的座机，不涉及电信业务资质。
- 别买 USB voice modem 走 PSTN：Win11 KB5074109 已封杀老 modem 驱动，且国内铜线正在退网。
- 自呼自己属个人事务，法律风险低；但如果改成打手机号/走云语音，需要企业资质与号码报备。
- 录音只在本机，别上传第三方；如需跑云 ASR，先脱敏。
- DSH 在 `repo\` 里拥有完整工具权限（能改文件、跑命令），别把话筒给陌生人。

## 10. 今晚（2026-11-04）调通的实测记录

详见容器根 `DEBUG-REPORT-2026-11-04.md`。核心证据：

- 14:16:46 投入 `e2e2-141646.wav`（问「用命令看一下当前目录里有哪些文件」）
- 14:17:12 ASR 完成（8.1s 音频）→ 后台 DSH
- 14:17:21 DSH 用**真实命令输出**回答：列出了 `freeswitch、hooks、logs、outbox、tasks、tools、tts` 等目录和 `README.md`、`config.yaml` 等文件
- 14:17:26 `bgapi originate ... user/100 &playback(...)` → Job-UUID `90dffa9c-…`，软电话 RINGING
- 14:18:26 无人接听（NO_ANSWER）自动收线 —— 振铃与播放链路本身已验证

# 调试报告 · 2026-11-04（老座机 AI 秘书）

> 给你白天看的一页纸。结论先说：**软件侧已经全线打通，只剩「座机硬件」这一腿**。
> 你睡前说「你自己调试」，我把 DSH 跑命令的沙箱问题、6001 被抢占、ffmpeg 在 SYSTEM 下找不到、
> 挂机钩子阻塞等一串坑都修完了，并且用软电话 + 投入录音的方式跑通了
> 「录音 → 转写 → DSH 执行命令 → 合成语音 → 回铃振铃」。

---

## 1. 现在的状态（一句话版）

| 环节 | 状态 | 证据 |
|---|---|---|
| 座机 → ATA → SIP 注册 | ⏳ 等硬件（HT801 未下单） | 软电话已用同一分机 100 验证通过 |
| 拨 6001 → FreeSWITCH 接听录音 | ✅ | `C:\fs\recordings` 出现 wav，日志 `context oldphone` + `oldphone_record` |
| Whisper 本地转写 | ✅ | 14:17:12 完成，8.1s 音频；中文口语基本对（偶有同音字） |
| DSH 执行任务（能读能写能跑命令） | ✅ 今晚修好 | 14:17:21 答复列出了真实 `ls` 结果 |
| 合成语音 + 回铃振铃 | ✅ | `Job-UUID 90dffa9c-…`，FS 日志 `Ring-Ready` → `RINGING` |
| 拿起听筒听结果 | ⏳ 等你接一次（今晚 60s 无人接听自动收线） | 下次响铃接起来即可 |
| 真实座机（HT801+复古机） | ⏳ 未购买 | 采购清单见聊天记录 |

## 2. 今晚做了什么（时间线）

- **12:19** 第一次真实「打电话派活」跑通：录音 6.4s → ASR → SYSTEM 身份跑 DSH → 76s 后写答复。
  但暴露出三个问题：① 挂机被钩子阻塞 12s；② SYSTEM 下 DSH 沙箱起不来（只能读不能跑命令）；
  ③ 回铃报 `[WinError 2]`（ffmpeg 不在 SYSTEM 的 PATH 里）。
- **12:2x** 修 ffmpeg 定位（`find_ffmpeg()` 绝对路径兜底）、ASR 提示词补「说话人可能自称『老座机』」、
  把 `listen` 改成「立刻返回 + 后台 worker」避免阻塞 FreeSWITCH。
- **12:3x–12:5x** 排查 DSH 沙箱：读了 `@deepseek-ai/dsh-sandbox-windows-acl` 源码，确认它要求
  「私有 temp 目录 + workspace-write 同时授权 workspace 和 temp」；试出 temp 必须在 workspace 之外。
- **13:5x–14:1x** 定案并重构：容器根只放环境（`.venv/.tmp/.dsh-home/.cache`），业务代码进 `repo\`；
  `config.yaml` 增 `agent.dsh.temp: C:/Users/Gavin/oldphone-ata/.tmp`；用计划任务同款令牌验证
  「workspace=repo\ws + temp=repo\.tmp」可跑命令。
- **14:16** 重注册 `OldPhoneWatcher` 计划任务（登录自启、用户令牌、pythonw），启动成功。
- **14:16:46** 投喂 `e2e2-141646.wav` → 14:17:12 转写 → 14:17:21 DSH 用真实命令输出回答 →
  14:17:26 回铃振铃 → 14:18:26 无人接听收线。**闭环成立**。

## 3. 关键证据（可复查）

- watcher 日志：`repo\logs\watch.log`
  ```
  2026-11-04 14:16:18 开始监听 C:\fs\recordings（基线 4 个文件，补处理 0 个）
  14:16:49 发现新录音 e2e2-141646.wav
  14:17:12 ASR 完成（音频 8.1s）: 老座机,请用命令看一下当前目录里有哪些文件,然后用一句话告诉我有没有Vimeo文件。
  14:17:21 电话里要念的答复： 当前目录里有 freeswitch、hooks、logs、outbox、tasks、tools、tts 这几个文件夹，
           还有 config.yaml、oldphone.py、README.md 和 requirements.txt。其中没有 Vimeo 文件。
  ```
  （「Vimeo」是 ASR 把 README 听错了，但 DSH 的目录列举是真的。）
- 回铃证据：`oldphone.py` 输出 `+OK Job-UUID: 90dffa9c-5b06-4972-926d-de350f06006a`；
  FreeSWITCH 日志 `Ring-Ready sofia/internal/100@10.13.162.128:49667!`、`Callstate Change DOWN -> RINGING`；
  最后 `Hangup ... [CS_CONSUME_MEDIA] [NO_ANSWER]`（响满 60 秒没人接）。
- 语音产物：`repo\tts\reply-20261104-141721.wav`（273 KB，8kHz 单声道）；
  完整答复同时在 `repo\outbox\reply-20261104-141721.txt`。

## 4. 今晚修掉的 7 个坑（都已写进 README 排错表）

1. **6001 没执行**：被 FreeSWITCH 默认拨号计划的 `valet_park`（`^((?!6000)60\d{2})$` 吃掉 6000-6099）抢走。
   → 分机 100 改用独立 context `oldphone`，拨号计划放 `conf/dialplan/oldphone.xml`。
2. **能振铃没声音**：`vars.xml` 默认用 STUN 把 `external_rtp_ip` 探成公网 IP，SDP 里填错地址。
   → 固定为 `10.13.162.128`（`tools/fix_fs_media_ip.ps1`，有备份）。
3. **挂机后 FS 卡 12s**：`api_hangup_hook` 是同步的，Whisper 加载期间通道无法销毁。
   → 彻底不用钩子，改 watcher 轮询录音目录。
4. **SYSTEM 身份跑 DSH 沙箱起不来**：报「缺少登录 SID，只能读文件」。
   → watcher 以用户令牌（计划任务 LogonType=3）启动后续流程。
5. **DSH 报 `Windows ACL temp root must be outside the workspace`**：temp 指进了项目根。
   → 目录重构：`repo\` 是 workspace，`.tmp\` 在容器根（兄弟目录）。
6. **DSH 能聊天但跑不了命令**（锁文件 `CreateFileW failed (Win32 5)` / `EPERM mkdir dsh-acl-locks`）：
   默认 `%TEMP%` 在降权/计划任务令牌下不可写。
   → `agent.dsh.temp` 固定到可写的 `.tmp`，并在 `dsh_env()` 里设 `TMP/TEMP/TMPDIR`。
7. **SYSTEM 下回铃 `[WinError 2]`**：ffmpeg 只在用户 PATH 里。
   → `find_ffmpeg()` 多路径兜底 + `config.yaml` 写绝对路径。

## 5. 现在还差什么

1. **硬件**：HT801（闲鱼二手 ¥100–180）+ 复古座机（¥50–300）。买前问清：单部实价/是否含 5V 电源/
   能否恢复出厂（admin/admin）/能否拍一段「接话机振铃」的视频。
2. **接听验证**：下次回铃响的时候接起来——听到 TTS 才算「人耳验收」。
   软电话里接听即可（MicroSIP 窗口会弹来电；也可以设置自动接听）。
3. **无人接听重呼**（可选）：现在 45s 没人接就断（`pbx.ring_timeout`），可以加「隔 2 分钟再打一次」。
4. **ASR 同音字**：`README`→`Vimeo`、`git`→`GIF`；电话 8kHz 窄带先天吃亏。
   可换 `model: "large-v3"`（更慢）、或让它先复述确认再执行。
5. **HT801 到货后**：改 `10.13.162.128:5060` 注册分机 100 → Offhook Auto-Dial 设 `6001` →
   拿起话筒应该直接连到 FreeSWITCH 并开始录音。

## 6. 你想自己验一遍（3 条命令）

```powershell
cd C:\Users\Gavin\oldphone-ata\repo
# 1) 现在 watcher 在不在
Get-ScheduledTask OldPhoneWatcher | Select TaskName, State
Get-Content .\logs\watch.log -Tail 5

# 2) 手动制造一次「电话」：把任意 8k wav 丢进录音目录
Copy-Item .\tts\selftest.wav C:\fs\recordings\manual-test.wav
# 等 10–20 秒看 watch.log，然后软电话会响（接起来听到答复）

# 3) 单独问 DSH（不经过电话）
..\.venv\Scripts\python.exe oldphone.py ask --text "用一句话说明当前项目是做什么的"
```

## 7. 文件地图（改过/新增）

| 文件 | 说明 |
|---|---|
| `repo\oldphone.py` | 主程序：加了 `find_ffmpeg()`、`spoken_text()`（电话口语压缩）、`PHONE_HINT`、`dsh_env()` 里设 temp、`listen` 派后台 worker |
| `repo\config.yaml` | 加 `agent.dsh.temp`、`agent.phone_reply_chars: 260`、`pbx.ring_timeout: 45`、ffmpeg 绝对路径 |
| `repo\tools\watch_recordings.py` | 新增：录音目录 watcher（单实例锁、基线忽略、1.5s 稳定判定） |
| `repo\tools\register_watcher_task.ps1` | 新增：注册 `OldPhoneWatcher` 登录自启任务 |
| `repo\tools\deploy_dialplan.ps1` | 新增：部署 `oldphone.xml` 到 FreeSWITCH 并 reloadxml |
| `repo\freeswitch\100.xml` | 加 `user_context=oldphone` |
| `repo\freeswitch\oldphone.xml` | 新拨号计划（替代 `01_oldphone.xml`，6001 → 接听录音） |
| `repo\README.md` | 全量重写：新目录、watcher 架构、DSH 沙箱两条硬规则、排错表 |
| `C:\Program Files\FreeSWITCH\conf\vars.xml` | `external_rtp_ip/external_sip_ip` 固定内网 IP（有 `.bak-oldphone` 备份） |

---

**下一步等你**：① 要不要下单 HT801 + 座机；② 回铃响起时接一次；③ 需不需要我把「无人接听重呼」加上。
## 8. 23:00 更新：bridge 模式（电话 → 当前桌面会话）+ 确定性回电

原来 `agent.mode: dsh` 是**另起一个 headless 会话**干活，和 GUI 里这间会话是两段上下文。
现在默认改成 `agent.mode: bridge`：电话里说的话会作为一条**用户消息**出现在当前桌面 DSH 会话里，
和 GUI 共享同一段上下文；回电也不再依赖 agent 执行命令，而是 watcher 监听会话日志自动回拨。

### 8.1 架构

```
座机/软电话 拨 6001 → FreeSWITCH 录音 → C:\fs\recordings\*.wav
                                    │
                     OldPhoneWatcher（计划任务，登录自启，用户令牌）
                                    │
                     listen-worker: Whisper 转写
                                    │
             dispatch() → bridge_send()
                     POST http://127.0.0.1:<DSH端口>/dsh-idle-watchdog/api/prompt
                     {chat, message:"【座机来电】…", provenance:"oldphone-ata/phone"}
                                    │
                     当前桌面 DSH 会话收到一条 user 消息 → agent 回答
                                    │
             watcher 每秒 check_phone_callback()
                     解压 session.v4.jsonl.zstd → 找到【座机来电】→ 等 turn/end
                     → 取最后一段回答 → spoken_text → edge-tts → ring_and_play
                                    │
                     座机振铃，接起来听总结
```

### 8.2 关键实现

| 位置 | 内容 |
|---|---|
| `oldphone.py` | `bridge_secret()` / `http_json()` / `bridge_find_url()`（netstat 自动找端口）/ `bridge_pick_chat()`（按 cwd 过滤）/ `bridge_phone_message()` / `bridge_send()` |
| `oldphone.py` | `write_pending()` / `read_pending()` / `clear_pending()` / `session_log_path()` / `read_session_events()` / `check_phone_callback()` |
| `config.yaml` | `agent.mode: bridge`；`bridge.{url,chat,cwd,secret_file,timeout,sessions_dir,callback_ttl_seconds}` |
| `tools/watch_recordings.py` | 主循环里每秒调用 `oldphone.check_phone_callback()` |
| `requirements.txt` | 新增 `zstandard>=0.23`（会话日志是 zstd 压缩） |
| 插件 | `dsh-idle-watchdog@1.2.0`，已进桌面 profile 的 `dsh.profile.bundles`，secret 在 `~/.dsh/idle-watchdog/api-secret` |

### 8.3 已验证

- 插件挂载：`GET /dsh-idle-watchdog/api/health` → `{"ok":true,"version":"1.2.0"}`；`/api/doctor` 全绿。
- 投递 1（纯文本）：`prompt-accepted`，`session-8aca49a6-…`，`via: exact`。
- 投递 2（wav 模拟电话）：21:21:13 watcher 发现 `bridge-test-212110.wav` → 21:21:51 ASR → 21:22:06 投递返回
  `{'ok': True, 'chat': 'session-8aca49a6-…', 'via': 'exact', 'resumed': False}`。
- 确定性回电单测（`tools/_callback_unit.py`，假会话日志）：
  `会话答复（电话里要念的）： 这是测试回答` → `TTS 完成 …30 KB` → `发起回呼: bgapi originate … user/100`
  → `check_phone_callback() == True`、`pending` 已清。
- watcher 已重启（22:08:16）加载新代码，日志 `repo\logs\watch.log`。

### 8.4 已知限制

1. 会话正忙时投递排队，HTTP 要 15–30 秒才返回（`bridge.timeout` 已设 60）。
2. 回电视为「这一轮 turn 结束」触发：长任务中途不会回电；900 秒（`callback_ttl_seconds`）内没答完就放弃。
3. 桌面端每次重启端口会变（3244 → 1762），`bridge.url: auto` 会自动探测。
4. 插件是启动时挂载的：装/升级插件后要重启一次 DSH 桌面端。
5. 当前**没有注册的 SIP 终端**（MicroSIP 的 exe 不见了、HT801 还没买），
   所以自动回拨会失败并记日志，听不到声音。

### 8.5 下次继续（按顺序）

```bat
cd C:\Users\Gavin\oldphone-ata\repo
# 1) watcher 在不在
Get-ScheduledTask OldPhoneWatcher | Select TaskName, State
Get-Content .\logs\watch.log -Tail 5

# 2) 装软电话（如果还想先听声验收）
#    官方 https://www.microsip.org/download/MicroSIP-3.22.23.zip 解压到
#    C:\Users\Gavin\oldphone-ata\tools\softphone\
#    账号：SIP Server 10.13.162.128 / User 100 / Password phone1234 / Media Encryption Disabled

# 3) 制造一次「电话」：把 8k wav 丢进录音目录
Copy-Item .\tts\selftest.wav C:\fs\recordings\manual-test.wav
# 看 watch.log：ASR → 投递 → 会话回答 → 自动回呼

# 4) 硬件到货后按 docs\hardware-checklist.md 配 HT801（SIP 注册 100、Offhook Auto-Dial=6001）
```

**当前状态**：`.tmp/phone-pending.json` 里还留着一条待回电记录（为排队中的两条测试消息预置）。
它会在会话处理到那条【座机来电】并答完后尝试回拨；由于没有终端，结果会是「回拨失败」记日志，属预期。

---

**下一步等用户**：① 买 HT801 + 复古座机（清单见 `repo\docs\hardware-checklist.md`）；
② 可选：重装 MicroSIP 做有声验收；③ 可选：加「无人接听重呼」。


## 9. 22:45 更新：软电话重装 + 本机 IP 变更（重要）

**软电话**：官方源 microsip.org 只有 ~2 KB/s、winget 装到 1 MB 卡死，改用 GitHub
`JFC-Group/JFC-microsip` v3.21.4.0 便携版（`JFC-MicroSIP-v3.21.4.0-JFC-1-Portable.zip`，
18.9 MB），解压到 `C:\Users\Gavin\oldphone-ata\tools\softphone\`（`microsip.exe`）。
账号写进 `MicroSIP.ini`（UTF-16）：server/domain = 电脑内网 IP、username/authID = 100、
password = phone1234（应用内加密存储）。注册结果：`User: 100@192.168.124.26`、
`Agent: MicroSIP/3.21.4`、`Ping-Status: Reachable`。

**IP 变更**：本机 IPv4 从 `10.13.162.128` 变成 `192.168.124.26`（DHCP）。FreeSWITCH 的
internal profile 仍绑旧 IP → 5060 无监听 → 软电话显示「Connecting...」、0 注册。
先用 `global_setvar local_ip_v4/external_rtp_ip/external_sip_ip` + `sofia profile internal restart`
热修验证通了（能注册、能回铃）。

**持久化**：把 `conf/vars.xml` 的 `external_rtp_ip` / `external_sip_ip` 改成 `$${local_ip_v4}`
（跟随本机 IP）。踩坑：PowerShell 的 `[regex]::Replace` 替换串里 `$$` 是转义 `$`，第一次写成
`${local_ip_v4}`，FS 展开成 `%{local_ip_v4}` 非法地址 → IPv4 profile 创建失败、5060 不监听。
第二次改用 `String.Replace('=${local_ip_v4}', '=$${local_ip_v4}')` 修好（脚本
`repo\tools\fix_fs_dynamic_ip2.ps1`，备份 `vars.xml.bak-oldphone-ip` / `-ip2`）。
现状：`sofia status` 4 profiles 1 alias、internal `sip:mod_sofia@192.168.124.26:5060` RUNNING、
`external_rtp_ip` = 192.168.124.26。

**回铃验收（两次）**：22:39:15 RINGING→ACTIVE→playback；22:41:38 RINGING →
22:41:45 ACTIVE → 播放 `softphone-test.wav` → 22:41:50 NORMAL_CLEARING。音频通道 PCMU/8000。

**注意**：DHCP 下电脑 IP 还可能变。FreeSWITCH 侧已自动跟随；但 **ATA/软电话的 SIP Server
必须手动改**（`ipconfig` 查新 IP）。建议路由器给电脑和 HT801 做 DHCP 静态保留。

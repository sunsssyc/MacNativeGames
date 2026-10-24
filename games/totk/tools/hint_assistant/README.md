# 卡关助手

模型按问题自己挑工具：最近一次磁盘存档、游戏自己的简体中文任务日志/地名/道具名、运行时的玩家位置，允许时还有游戏画面。不会修改存档；存档不代表尚未保存的实时进度，也不保证模型推理出的解法正确。

## 露珠旅途伙伴

小地图上方的露珠头像是常驻入口。点击或按 `8` 展开右侧聊天面板；展开时暂停游戏，收起时仅释放助手自己的暂停，不解除设置菜单的暂停。当前会话保留文字问答，最多显示最近 12 轮。

点击面板内「语音」开始录音，再点「停止」立即关闭麦克风。识别文字留在输入框，可修改后点击「发送」；停止和识别完成均不自动求助。录音中可点「取消录音」，或按 Esc 取消并保留原有草稿。V 不再是录音快捷键。首次使用会按需申请语音识别和麦克风权限，授权后再次点击语音。使用系统本机中文识别；本机识别不可用、无麦克风或权限被拒绝时，仍可文字提问。录音最多 60 秒，切换到其他应用立即取消。打开助手不录音、不自动求助。这是语音输入，不是连续实时通话。

回复每段最多 3 行，`▼` 表示还有下一段：输入框为空时按回车，或点一下文字，翻到下一段。

## 朗读（可选）

默认关闭。面板上的「朗读」是开关，打开后朗读屏幕上的回复以及之后的每条回复，每段读完自动翻页；设置记在 `assistant.json` 的 `voice.enabled`。收起面板、按 Esc 或发出新问题都会停止朗读。

声音有两种来源：

1. **系统声音**（不用下载）：macOS 自带的中文声音。语音组件没装、还没录参考声音或合成出错时都用它。
2. **克隆声音**：Qwen3-TTS 0.6B Base 的 4bit MLX 版（`mlx-community/Qwen3-TTS-12Hz-0.6B-Base-4bit`，Apache-2.0），通过 `mlx-audio==0.6.1` 运行。点面板下方的「下载语音」安装：用游戏助手自己的 Python 3.14 建虚拟环境（约 450 MB）并下载模型（约 1.7 GB），都放在 `~/Library/Application Support/MacNativeGames/TOTK/tts/`，不打包进 App。再点「录我的声音」照着屏幕读一句话（3–20 秒），之后就用这个声音朗读。

这个模型没有自带音色：不给参考声音时它停不下来（实测“你好”两个字生成了 655 秒），所以必须先录参考声音。**只录你自己的声音，或已经同意的人的声音**；不要用游戏角色的配音或从游戏、视频里截取的别人的声音。

合成只在面板打开、游戏暂停时进行（模型和游戏共用 GPU）：发出问题时先加载模型，回答到达后逐段合成。空闲 120 秒（`voice.unload_after_seconds`）后释放模型，约 1.9 GB 内存。M1 Max 实测：加载 2.6 秒；预热后约 2 秒合成 6 秒的话。

命令行：`run.py voice status`、`run.py voice install`、`run.py voice reference --audio 录音.m4a '录音里的原话'`（换参考声音）、`run.py voice say '一句话' --out a.wav`。头像为生成的露珠风格插画。

## 启用和游戏操作

需要 Python 3.14（标准库 `compression.zstd`），以及已登录的 Claude Code 或 Codex；Vertex AI 是后备，可使用本机已有的 gcloud 项目和认证。不会创建云资源或更改登录配置。

```sh
python3.14 games/totk/tools/hint_assistant/run.py config --init
```

游戏中首次打开卡关助手时，可直接点击「启用助手」。也可编辑 `~/Library/Application Support/MacNativeGames/TOTK/assistant.json`，将 `enabled` 设为 `true`。启用后直接进入提问面板，下一次主动求助才会读取信息。首次默认关闭；开启后，求助时模型按需读取的存档内容和游戏文本会发送给可用模型服务。`allow_screenshot` 默认 `false`，需要看当前游戏画面时自行设为 `true`。`allow_actions` 默认 `false`，见下文「代操作」。

重新构建的游戏里按 `8` 打开助手，可在输入框描述问题，点击「发送」或按回车提交，并接着上一条回答追问；打开面板本身不发起模型请求。也可点击「根据进度给提示」，再按 `8` 或「更具体一点」依次获得“去哪里 → 用什么 → 完整解法”；`Shift+8` 开始新的问题，`Esc` 关闭并取消正在进行的求助。失败后按 `8` 重试同一级。输入问题时面板接收键盘焦点。启用、提问、等待、结果和失败提示共用游戏风格面板、分隔线与按钮；可用鼠标取消、重试或查看下一档提示，长结果可滚动。每个后端最长 45 秒（`timeout_seconds`），一次求助的所有后端合计最长 150 秒（`total_timeout_seconds`），游戏比合计上限多等 10 秒，超时后取消，不自动重试。助手服务按需启动，空闲时仅等待本地请求，不持续读取游戏信息；游戏退出后自动停止。

原生游戏从 `/opt/homebrew/bin/python3.14`、`/usr/local/bin/python3.14`、标准 Python.framework 路径发现 Python；其他安装位置可设置 `TOTK_HINT_PYTHON`。游戏工作目录应为 `games/totk`，打包器会复制助手源码进应用；Python 和模型客户端需由用户安装，不包含在 app 中。底层模型/项目名可以在配置中覆盖，应使用自己账号可访问的模型。

## 命令行和 MCP

```sh
python3.14 games/totk/tools/hint_assistant/run.py backends
python3.14 games/totk/tools/hint_assistant/run.py state --romfs /path/to/romfs --save-root /path/to/profile/save
python3.14 games/totk/tools/hint_assistant/run.py hint --tier 1 --question '下一步去哪里？'
python3.14 games/totk/tools/hint_assistant/run.py mcp
```

MCP 使用标准输入/输出逐行 JSON-RPC。始终提供 `game_state`、`quest_log`、`search_text`（存档与游戏文本）和 `runtime_state`、`wait_state`（运行时只读）；只有传入 `--allow-screenshot` 才提供 `screenshot`，只有传入 `--allow-actions` 才提供 `press_button`、`stop_action`。所有诊断写 stderr；截图通过已有游戏命令通道生成，不抓取其他应用。`--config`、`--romfs` 和 `--save-root` 可用于独立配置和测试存档。

自动后端顺序：Claude Code → Codex → Claude Code 的 Vertex AI provider → Vertex AI REST。前一个不可用、失败或超时后才继续；取消不会尝试后备。每个后端默认最长 45 秒，合计不超过 150 秒，剩余不足 5 秒时不再启动下一个后端。第一档成功后，同一会话的后续档位会带上之前提示。

`assistant.json` 保存设置，`hint-request.json` / `hint-response.json` 是原子写入的本机 IPC；缓存和模型临时运行目录位于 `~/Library/Caches/MacNativeGames/TOTK/hint-assistant`。截图保留最近几份。

## 离线验证

```sh
python3.14 -m unittest discover -s games/totk/tools/hint_assistant/tests -v
```

测试只用合成存档、临时目录及模型桩：覆盖后备顺序、取消、三级上下文、旧响应丢弃、启动请求竞态、MCP 错误恢复、中文当前任务日志与输出限制。不连接模型，不读取玩家真实存档。完整游戏画面、真实存档版本和真实后端端到端验证需在用户已启用的环境中另行完成。


## 直接游戏运行时工具

CLI 与 MCP 共用 runtime-request/runtime-response JSON 通道，由游戏主线程处理；不需要截图权限。

| MCP 工具 | CLI | 含义 |
|---|---|---|
| runtime_state | `live state` | 当前进程、玩家对象是否存在、当前坐标、采样时间、助手暂停状态 |
| press_button | `live press --button down --duration-ms 150` | 一次 30–1000 ms 的控制器输入，结束后返回状态（仅代操作授权时） |
| stop_action | `live stop` | 释放工具持有的按键（仅代操作授权时） |
| wait_state | `live wait --duration-ms 500` | 等待后再观察；不推进已暂停的游戏 |

执行：`python3.14 games/totk/tools/hint_assistant/run.py live state`。普通 CLI 不调用模型。
按键包括 a/b/x/y、l/r/zl/zr、plus/minus、up/down/left/right、forward/backward/strafe_left/strafe_right、look_left/look_right/look_up/look_down。
组合方式：观察 → 一次输入 → 等待 → 再观察。工具成功表示输入已经完成，不保证菜单切换、移动或战斗目标达成。

当前版本只实现玩家对象和坐标的实时读取。`no_player` 不能区分标题菜单、加载或过场；实时血量、任务状态和场景名称尚未实现，返回未知。原 `game_state`、`quest_log` 仍明确属于历史存档。

提问只提交问题和会话上下文，不自动采集运行时、存档或画面。助手按问题选择工具；旧 prefetch_state 配置不再触发预读取。玩家对象可能在标题菜单存在，因此 runtime_state 的 world_state 保持 unknown，不凭对象存在或坐标推断已进入游戏。

### 代操作

默认关闭。`assistant.json` 的 `allow_actions` 设为 `true` 后，面板上才出现「允许操作」；点一下只对下一个输入的问题有效，发送后自动复位。三道闸各自独立：

1. 服务只在 `allow_actions` 为真、请求里有 `"actions": true` 且是输入的问题时，才把 `press_button`、`stop_action` 交给模型（Claude Code 的允许清单、MCP 工具列表、Vertex 工具列表都按此筛选）。
2. 游戏只接受当前进行中、且被授权的那次求助的按键，每次求助最多 6 次；其他时候回复 `actions_not_allowed`，包括命令行 `live press`。
3. 操作时面板显示「露珠正在操作游戏」；Esc、收起面板、回答结束或超时都会立刻松开按键并收回授权。

助手暂停期间执行输入会短暂解除助手自己的暂停，输入结束后恢复；其他暂停来源保持原状。请求带唯一 ID 和时效，旧响应不会当作新响应。输入最多持续 1 秒。

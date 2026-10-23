# 卡关助手

读取最近一次磁盘存档及游戏自己的简体中文任务日志、地名、道具名；不会修改存档。它不能读取尚未保存的实时进度，也不保证模型推理出的解法正确。

## 启用和游戏操作

需要 Python 3.14（标准库 `compression.zstd`），以及已登录的 Claude Code 或 Codex；Vertex AI 是后备，可使用本机已有的 gcloud 项目和认证。不会创建云资源或更改登录配置。

```sh
python3.14 games/totk/tools/hint_assistant/run.py config --init
```

编辑 `~/Library/Application Support/MacNativeGames/TOTK/assistant.json`，将 `enabled` 设为 `true`。首次默认关闭；开启后，按键求助会把存档摘要/游戏文本发送给可用模型服务。`allow_screenshot` 默认 `false`，需要看当前游戏画面时自行设为 `true`。

重新构建的游戏里按 `8`，依次获得“去哪里 → 用什么 → 完整解法”；`Shift+8` 开始新的问题，`Esc` 关闭并取消正在进行的求助。失败后按 `8` 重试同一级。窗口不夺取游戏焦点。助手服务按需启动，游戏退出后自动停止。

原生游戏从 `/opt/homebrew/bin/python3.14`、`/usr/local/bin/python3.14`、标准 Python.framework 路径发现 Python；其他安装位置可设置 `TOTK_HINT_PYTHON`。游戏工作目录应为 `games/totk`，打包器会复制助手源码进应用；Python 和模型客户端需由用户安装，不包含在 app 中。底层模型/项目名可以在配置中覆盖，应使用自己账号可访问的模型。

## 命令行和 MCP

```sh
python3.14 games/totk/tools/hint_assistant/run.py backends
python3.14 games/totk/tools/hint_assistant/run.py state --romfs /path/to/romfs --save-root /path/to/profile/save
python3.14 games/totk/tools/hint_assistant/run.py hint --tier 1 --question '下一步去哪里？'
python3.14 games/totk/tools/hint_assistant/run.py mcp
```

MCP 使用标准输入/输出逐行 JSON-RPC，工具为 `game_state`、`quest_log`、`search_text`，只有明确传入 `--allow-screenshot` 才提供 `screenshot`。所有诊断写 stderr；截图通过已有游戏命令通道生成，不抓取其他应用。`--config`、`--romfs` 和 `--save-root` 可用于独立配置和测试存档。

自动后端顺序：Claude Code → Codex → Claude Code 的 Vertex AI provider → Vertex AI REST。前一个不可用、失败或超时后才继续；取消不会尝试后备。每个后端默认最长 120 秒。第一档成功后，同一会话的后续档位会带上之前提示。

`assistant.json` 保存设置，`hint-request.json` / `hint-response.json` 是原子写入的本机 IPC；缓存和模型临时运行目录位于 `~/Library/Caches/MacNativeGames/TOTK/hint-assistant`。截图保留最近几份。

## 离线验证

```sh
python3.14 -m unittest discover -s games/totk/tools/hint_assistant/tests -v
```

测试只用合成存档、临时目录及模型桩：覆盖后备顺序、取消、三级上下文、旧响应丢弃、启动请求竞态、MCP 错误恢复、中文当前任务日志与输出限制。不连接模型，不读取玩家真实存档。完整游戏画面、真实存档版本和真实后端端到端验证需在用户已启用的环境中另行完成。

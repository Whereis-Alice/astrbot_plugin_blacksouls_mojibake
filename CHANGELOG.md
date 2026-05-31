# Changelog

## v0.2.2

- 修复爱丽丝触发路径可能出现的二次奈亚语编码：现在直接重建发送文本为一次转换结果。
- 爱丽丝触发回复默认关闭可逆字节标记，减少 `・83`、`・84`、`・EF` 这类可逆十六进制片段。
- 增加 `alice_trigger.lossless_encode`，需要精确可逆时可以手动开启。
- 改用 `@filter.llm_tool` 注册固定工具 `convert_nyaya_language`，提高 AstrBot LLM 工具可见性。
- 增加 LLM 请求提示，用户提到奈亚语/乱码转换时优先使用 `convert_nyaya_language`，不要绕去调用 Python 工具。

## v0.2.1

- 补回显式命令触发：默认 `/nyaya` 转奈亚语、`/unyaya` 翻译奈亚语、`/nyaya_help` 查看帮助。
- 命令仍然是明确触发，不会恢复“用户直接发乱码就自动抢答”的行为。
- README 增加命令说明，配置新增 `commands` 分组。

## v0.2.0

- 将乱码统一命名为“奈亚语”。
- 调整“爱丽丝里德尔”触发逻辑：不再直接发送固定回复，而是在 LLM 按原人格回复后，将回复转换成奈亚语。
- 爱丽丝触发默认会主动唤醒 LLM，可通过 `alice_trigger.wake_llm` 关闭。
- 移除直接收到乱码就自动翻译的抢答行为，改为注册 `convert_nyaya_language` LLM 工具。
- 整理配置结构，按 `general`、`llm_tool`、`alice_trigger`、`codec` 分组。
- 增加 debug 日志输出，记录工具转换和爱丽丝触发转换的原文与结果。
- 重写 README，使安装、功能和配置说明更清楚。

## v0.1.0

- 初始版本：中文/CP932 乱码互转。
- 添加爱丽丝里德尔触发回复和手动 `/bsalice` 命令。
- 添加直接发送乱码时的自动翻译。
- 添加可逆乱码模式，避免命令转换丢字节。

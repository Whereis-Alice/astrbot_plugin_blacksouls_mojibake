# 奈亚语转换插件

把中文和 BLACKSOULS 风格乱码互相转换的 AstrBot 插件。这里把这类乱码统称为“奈亚语”。

奈亚语的效果来自一种经典乱码现象：中文 UTF-8 字节被错误地按日文 CP932 / Shift-JIS 解码，所以会出现 `陲ｫ逋ｼ迴ｾ`、`蜿ｯ謔ｲ逧・84` 这种文字。

## 功能

### 1. 显式命令转换

默认命令：

```text
/nyaya 文本
/unyaya 奈亚语文本
/nyaya_help
```

也有中文别名：

```text
/奈亚语 文本
/解奈亚语 奈亚语文本
/奈亚语帮助
```

这类命令是明确触发，不会影响普通聊天。

### 2. LLM 工具转换

插件会按 AstrBot 推荐的 `FunctionTool` 方式注册一个 LLM 工具，默认名称是：

```text
convert_nyaya_language
```

当用户明确要求 bot 转换奈亚语时，LLM 可以调用这个工具。

示例说法：

```text
把“爱丽丝里德尔”转成奈亚语
翻译这段奈亚语：陲ｫ逋ｼ迴ｾ
这句奈亚语是什么意思：蜿ｯ謔ｲ逧・84
```

插件不会再因为用户单纯发送乱码就自动抢答。是否调用工具由 LLM 根据用户请求决定。

为了避免模型绕去调用 Python 工具，插件默认会在相关请求里提示 LLM：转换奈亚语时使用 `convert_nyaya_language`，不要使用 `astrbot_execute_python` 导入插件源码。

### 3. 爱丽丝里德尔触发

当用户消息命中配置里的触发词，例如：

```text
爱丽丝里德尔
爱丽丝·里德尔
```

bot 仍然会按原本的人格、上下文和模型能力正常生成回复。插件只会在 LLM 回复完成后，把这条回复转换成奈亚语再发出去。

也就是说，插件不会替换人格，也不会改写回复内容，只改变最终显示语言。

默认情况下，命中触发词会主动唤醒 LLM。也就是说在群聊里即使没有 @ bot，只要说出触发词，bot 也会按当前人格回复一次，然后这次回复会被转成奈亚语。可以通过 `alice_trigger.wake_llm` 关闭这个行为。

爱丽丝触发回复默认使用更像原始 BLACKSOULS 的非可逆奈亚语。需要精确可逆时，可以打开 `alice_trigger.lossless_encode`。如果 `codec.lossless_style` 保持默认的 `hidden`，用户不会看到 `83/84/EF` 这类标记。

### 3. Debug 日志

默认会在 AstrBot debug 日志里输出转换前后文本，方便排查：

```text
[astrbot_plugin_blacksouls_mojibake] tool conversion | direction=to_nyaya | original=... | converted=...
[astrbot_plugin_blacksouls_mojibake] alice_response conversion | direction=to_nyaya | original=... | converted=...
```

如果不想在日志里出现聊天内容，可以关闭配置：

```text
general.debug_log_conversions = false
```

## 配置说明

配置被整理成 5 组。

### general

基础开关和调试日志。

- `enabled`：启用插件。
- `debug_log_conversions`：是否在 debug 日志输出转换前后文本。
- `debug_max_chars`：每段日志最多输出多少字符。

### llm_tool

LLM 工具配置。

- `enabled`：是否启用奈亚语转换工具。
- `description`：给 LLM 看的工具说明，决定它什么时候调用工具。
- `inject_usage_hint`：当用户提到奈亚语/乱码/转换/翻译时，提示 LLM 优先使用 `convert_nyaya_language`，不要用 Python 工具。
- `request_keywords`：哪些关键词会触发 LLM 工具提示，默认包含“奈亚语、乱码、转换、翻译、解读”等。
- `auto_mode_decode_min_score`：工具 `auto` 模式判断文本是否像奈亚语的阈值。

### commands

显式命令配置。

- `enabled`：启用命令转换。
- `to_nyaya`：中文转奈亚语命令，默认 `/nyaya,/奈亚语`。
- `to_chinese`：奈亚语转中文命令，默认 `/unyaya,/解奈亚语`。
- `help`：帮助命令，默认 `/nyaya_help,/奈亚语帮助`。

### alice_trigger

爱丽丝触发配置。

- `enabled`：启用触发。
- `wake_llm`：命中触发词时主动唤醒 LLM。
- `lossless_encode`：爱丽丝回复是否使用可逆奈亚语。默认关闭，更像游戏乱码。
- `trigger_phrases`：触发词列表。
- `match_mode`：`contains` 表示消息包含触发词即可触发；`exact` 表示整句完全相等才触发。

### codec

奈亚语编码细节，通常不用改。

- `lossless_encode`：默认开启。开启后会生成可逆奈亚语，可以稳定转回中文。
- `lossless_style`：可逆信息的保存方式。默认 `hidden`，使用零宽字符隐藏字节；`visible` 会显示成 `・84` 这类文本标记。
- `invalid_marker`：可逆标记的前缀，默认 `・`。
- `unknown_chars`：翻译旧乱码时视为未知字节的字符，默认 `・?`。
- `uncertain_char`：无法确定的字显示成什么，默认 `□`。
- `wrong_encoding`：错读编码，默认 `cp932`。

## 可逆奈亚语

原始 BLACKSOULS 乱码有时会丢字节，所以并不总是可逆。命令和 LLM 工具默认启用“可逆奈亚语”，并且默认用隐藏零宽字符保存字节信息。视觉上大致像这样：

```text
的 -> 逧・
丝 -> 荳・
```

实际文本里 `・` 后面带有用户看不见的零宽字符，用来保存原始字节，所以工具可以精确还原。

如果把 `codec.lossless_style` 改成 `visible`，才会显示成：

```text
的 -> 逧・84
丝 -> 荳・9D
```

`83`、`84`、`85`、`EF` 这类内容是原始 UTF-8 字节的十六进制标记，用来保证可逆。

如果关闭 `codec.lossless_encode`，显示会更像原始乱码，不过翻译回中文时可能出现 `□`。爱丽丝触发回复单独使用 `alice_trigger.lossless_encode`，默认关闭。

注意：隐藏零宽字符模式依赖聊天平台保留这些不可见字符。如果平台或复制过程把零宽字符过滤掉，仍然会退化成旧式不可逆乱码。

## 安装

把本仓库目录放进 AstrBot 的插件目录，然后重载插件即可。

仓库根目录就是插件根目录，主要文件如下：

```text
main.py
codec.py
_conf_schema.json
metadata.yaml
requirements.txt
```

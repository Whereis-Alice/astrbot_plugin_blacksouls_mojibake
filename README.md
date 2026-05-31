# BLACKSOULS 乱码转换

一个给 AstrBot 用的 BLACKSOULS 梗向插件：把中文转成 UTF-8 被 CP932/Shift-JIS 错读后的乱码，也能把这类乱码尽量翻译回中文。

## 功能

- `/bsmoji 文本`：中文转 BLACKSOULS 风格乱码。
- `/bscn 乱码`：把乱码翻译回中文。
- `/bsalice`：随机发一条爱丽丝风格低语，并转成乱码。
- `/bshelp`：查看命令。
- 直接发乱码给 bot：插件会自动尝试翻译。
- 说出“爱丽丝里德尔”：bot 会回复一次可转换的乱码低语。

所有命令、触发词、回复文本、自动翻译阈值都可以在 `_conf_schema.json` 对应的 AstrBot 配置页修改。

## 可逆乱码

经典 CP932 乱码遇到某些 UTF-8 字节会丢信息，所以插件默认启用“可逆乱码”。无效字节会写成类似：

```text
・84
```

这样看起来仍然像旧网页乱码，但可以再用 `/bscn` 精确转回中文。如果想更像原始 BLACKSOULS 文本，可以把 `lossless_encode` 关掉，但转换回来可能会出现 `□`。

## 配置建议

- 想让群里少误触发：提高 `auto_decode_min_score`。
- 想更容易翻译短乱码：降低 `auto_decode_min_score` 和 `auto_decode_min_length`。
- 想换命令：修改 `encode_command`、`decode_command`、`alice_command`。
- 想换触发台词：修改 `trigger_replies`。


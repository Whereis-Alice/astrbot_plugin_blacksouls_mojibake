from __future__ import annotations

import random
import time
from dataclasses import dataclass
from typing import Any

from astrbot.api import AstrBotConfig, logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.star import Context, Star, register

try:
    from .codec import (
        DEFAULT_INVALID_MARKER,
        DEFAULT_SOURCE_ENCODING,
        DEFAULT_UNCERTAIN_CHAR,
        DEFAULT_UNKNOWN_CHARS,
        DEFAULT_WRONG_ENCODING,
        decode_from_mojibake,
        decode_with_score,
        encode_to_mojibake,
    )
except ImportError:
    from codec import (  # type: ignore[no-redef]
        DEFAULT_INVALID_MARKER,
        DEFAULT_SOURCE_ENCODING,
        DEFAULT_UNCERTAIN_CHAR,
        DEFAULT_UNKNOWN_CHARS,
        DEFAULT_WRONG_ENCODING,
        decode_from_mojibake,
        decode_with_score,
        encode_to_mojibake,
    )


PLUGIN_ID = "astrbot_plugin_blacksouls_mojibake"
PLUGIN_VERSION = "0.1.0"
PLUGIN_DESC = "BLACKSOULS 风格 UTF-8/CP932 乱码转换、自动翻译和爱丽丝触发回复"
PLUGIN_REPO = "https://github.com/Whereis-Alice/astrbot_plugin_blacksouls_mojibake"

DEFAULT_ALICE_REPLIES = [
    "落入白兔的洞穴之中\n可悲的愚蠢的小姑娘爱丽丝",
    "被发现-被发现-被找到-被知道-被确定-被发觉-被看到-被确认-被察觉--被理解",
    "就连这镜子里 也无法映出梦想与希望\n看呀 是爱哭鬼 爱丽丝",
]


@dataclass(frozen=True)
class PluginSettings:
    enabled: bool
    source_encoding: str
    wrong_encoding: str
    invalid_marker: str
    unknown_chars: str
    uncertain_char: str
    lossless_encode: bool
    encode_command: str
    decode_command: str
    alice_command: str
    help_command: str
    status_command: str
    auto_decode_enabled: bool
    auto_decode_min_score: int
    auto_decode_min_length: int
    auto_decode_template: str
    auto_decode_stop_event: bool
    trigger_enabled: bool
    trigger_phrases: list[str]
    trigger_match_mode: str
    trigger_cooldown_seconds: int
    trigger_replies: list[str]
    trigger_reply_template: str
    trigger_stop_event: bool


def _clean_text(value: Any, default: str = "") -> str:
    text = str(value or "").strip()
    return text or default


def _read_bool(value: Any, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"1", "true", "yes", "on", "enabled"}:
            return True
        if lowered in {"0", "false", "no", "off", "disabled"}:
            return False
    if value is None:
        return default
    return bool(value)


def _read_int(value: Any, default: int, *, minimum: int = 0, maximum: int = 999999) -> int:
    try:
        result = int(value)
    except (TypeError, ValueError):
        result = default
    return min(maximum, max(minimum, result))


def _read_list(value: Any, default: list[str]) -> list[str]:
    if isinstance(value, list):
        items = [_clean_text(item) for item in value]
        return [item for item in items if item]
    if isinstance(value, str):
        items = [
            item.strip()
            for item in value.replace("，", ",").replace("；", ";").split(";")
            for item in item.split(",")
        ]
        return [item for item in items if item] or default
    return default


def _split_command_aliases(value: str) -> list[str]:
    raw = _read_list(value, [])
    if raw:
        return raw
    text = _clean_text(value)
    return [text] if text else []


def _match_command(text: str, command_value: str) -> tuple[str, str] | None:
    stripped = text.strip()
    for command in _split_command_aliases(command_value):
        if stripped == command:
            return command, ""
        if stripped.startswith(command):
            rest = stripped[len(command) :]
            if not rest or rest[0].isspace():
                return command, rest.strip()
    return None


@register(PLUGIN_ID, "Huli3", PLUGIN_DESC, PLUGIN_VERSION, PLUGIN_REPO)
class BlackSoulsMojibakePlugin(Star):
    """BLACKSOULS-style mojibake toy plugin."""

    def __init__(
        self,
        context: Context,
        config: AstrBotConfig | dict[str, Any] | None = None,
    ) -> None:
        super().__init__(context, config)
        self.config = config or {}
        self._last_trigger_at: dict[str, float] = {}

    async def initialize(self) -> None:
        logger.info("[%s] initialized", PLUGIN_ID)

    def _cfg(self, key: str, default: Any) -> Any:
        if hasattr(self.config, "get"):
            return self.config.get(key, default)
        return default

    def _settings(self) -> PluginSettings:
        match_mode = _clean_text(self._cfg("trigger_match_mode", "contains"), "contains")
        if match_mode not in {"contains", "exact"}:
            match_mode = "contains"

        return PluginSettings(
            enabled=_read_bool(self._cfg("enabled", True), True),
            source_encoding=_clean_text(
                self._cfg("source_encoding", DEFAULT_SOURCE_ENCODING),
                DEFAULT_SOURCE_ENCODING,
            ),
            wrong_encoding=_clean_text(
                self._cfg("wrong_encoding", DEFAULT_WRONG_ENCODING),
                DEFAULT_WRONG_ENCODING,
            ),
            invalid_marker=_clean_text(
                self._cfg("invalid_marker", DEFAULT_INVALID_MARKER),
                DEFAULT_INVALID_MARKER,
            ),
            unknown_chars=_clean_text(
                self._cfg("unknown_chars", DEFAULT_UNKNOWN_CHARS),
                DEFAULT_UNKNOWN_CHARS,
            ),
            uncertain_char=_clean_text(
                self._cfg("uncertain_char", DEFAULT_UNCERTAIN_CHAR),
                DEFAULT_UNCERTAIN_CHAR,
            ),
            lossless_encode=_read_bool(self._cfg("lossless_encode", True), True),
            encode_command=_clean_text(self._cfg("encode_command", "/bsmoji"), "/bsmoji"),
            decode_command=_clean_text(self._cfg("decode_command", "/bscn"), "/bscn"),
            alice_command=_clean_text(self._cfg("alice_command", "/bsalice"), "/bsalice"),
            help_command=_clean_text(self._cfg("help_command", "/bshelp"), "/bshelp"),
            status_command=_clean_text(self._cfg("status_command", "/bsstatus"), "/bsstatus"),
            auto_decode_enabled=_read_bool(self._cfg("auto_decode_enabled", True), True),
            auto_decode_min_score=_read_int(
                self._cfg("auto_decode_min_score", 6),
                6,
                minimum=1,
                maximum=100,
            ),
            auto_decode_min_length=_read_int(
                self._cfg("auto_decode_min_length", 6),
                6,
                minimum=1,
                maximum=1000,
            ),
            auto_decode_template=_clean_text(
                self._cfg("auto_decode_template", "黑魂语翻译：\n{decoded}"),
                "黑魂语翻译：\n{decoded}",
            ),
            auto_decode_stop_event=_read_bool(
                self._cfg("auto_decode_stop_event", True),
                True,
            ),
            trigger_enabled=_read_bool(self._cfg("trigger_enabled", True), True),
            trigger_phrases=_read_list(
                self._cfg("trigger_phrases", ["爱丽丝里德尔", "爱丽丝·里德尔"]),
                ["爱丽丝里德尔", "爱丽丝·里德尔"],
            ),
            trigger_match_mode=match_mode,
            trigger_cooldown_seconds=_read_int(
                self._cfg("trigger_cooldown_seconds", 30),
                30,
                minimum=0,
                maximum=86400,
            ),
            trigger_replies=_read_list(
                self._cfg("trigger_replies", DEFAULT_ALICE_REPLIES),
                DEFAULT_ALICE_REPLIES,
            ),
            trigger_reply_template=_clean_text(
                self._cfg("trigger_reply_template", "{garbled}"),
                "{garbled}",
            ),
            trigger_stop_event=_read_bool(self._cfg("trigger_stop_event", True), True),
        )

    def _encode(self, text: str, settings: PluginSettings) -> str:
        return encode_to_mojibake(
            text,
            source_encoding=settings.source_encoding,
            wrong_encoding=settings.wrong_encoding,
            invalid_marker=settings.invalid_marker,
            lossless=settings.lossless_encode,
        )

    def _decode(self, text: str, settings: PluginSettings) -> str:
        return decode_from_mojibake(
            text,
            source_encoding=settings.source_encoding,
            wrong_encoding=settings.wrong_encoding,
            invalid_marker=settings.invalid_marker,
            unknown_chars=settings.unknown_chars,
            uncertain_char=settings.uncertain_char,
        )

    def _help_text(self, settings: PluginSettings) -> str:
        return (
            "BLACKSOULS 乱码插件\n"
            f"- 转成乱码：{settings.encode_command} 中文文本\n"
            f"- 翻译乱码：{settings.decode_command} 乱码文本\n"
            f"- 爱丽丝低语：{settings.alice_command}\n"
            f"- 状态：{settings.status_command}\n\n"
            "也可以直接发送 CP932/Shift-JIS 风格乱码，插件会自动尝试翻译。"
        )

    def _status_text(self, settings: PluginSettings) -> str:
        return (
            "BLACKSOULS 乱码插件状态：\n"
            f"- 启用：{settings.enabled}\n"
            f"- 正文编码：{settings.source_encoding}\n"
            f"- 错读编码：{settings.wrong_encoding}\n"
            f"- 可逆乱码：{settings.lossless_encode}\n"
            f"- 无效字节标记：{settings.invalid_marker}XX\n"
            f"- 自动翻译：{settings.auto_decode_enabled}\n"
            f"- 自动翻译阈值：{settings.auto_decode_min_score}\n"
            f"- 爱丽丝触发：{settings.trigger_enabled}\n"
            f"- 触发词：{', '.join(settings.trigger_phrases)}"
        )

    def _render_template(self, template: str, **values: str) -> str:
        try:
            return template.format(**values)
        except Exception:
            return template

    def _matches_trigger(self, text: str, settings: PluginSettings) -> bool:
        normalized = text.strip()
        if not normalized:
            return False
        for phrase in settings.trigger_phrases:
            if settings.trigger_match_mode == "exact" and normalized == phrase:
                return True
            if settings.trigger_match_mode == "contains" and phrase in normalized:
                return True
        return False

    def _trigger_on_cooldown(self, event: AstrMessageEvent, settings: PluginSettings) -> bool:
        if settings.trigger_cooldown_seconds <= 0:
            return False
        key = _clean_text(getattr(event, "unified_msg_origin", ""), "unknown")
        now = time.time()
        last = self._last_trigger_at.get(key, 0.0)
        if now - last < settings.trigger_cooldown_seconds:
            return True
        self._last_trigger_at[key] = now
        return False

    def _build_alice_reply(self, settings: PluginSettings) -> str:
        plain = random.choice(settings.trigger_replies or DEFAULT_ALICE_REPLIES)
        garbled = self._encode(plain, settings)
        return self._render_template(
            settings.trigger_reply_template,
            plain=plain,
            garbled=garbled,
        )

    def _is_configured_command(self, text: str, settings: PluginSettings) -> bool:
        return any(
            _match_command(text, command)
            for command in (
                settings.encode_command,
                settings.decode_command,
                settings.alice_command,
                settings.help_command,
                settings.status_command,
            )
        )

    @filter.regex(r"(?s).*")
    async def on_any_message(self, event: AstrMessageEvent):
        settings = self._settings()
        if not settings.enabled:
            return

        text = _clean_text(getattr(event, "message_str", ""))
        if not text:
            return

        encode_match = _match_command(text, settings.encode_command)
        if encode_match:
            payload = encode_match[1]
            if not payload:
                yield event.plain_result(f"用法：{settings.encode_command} 中文文本")
            else:
                yield event.plain_result(self._encode(payload, settings))
            event.stop_event()
            return

        decode_match = _match_command(text, settings.decode_command)
        if decode_match:
            payload = decode_match[1]
            if not payload:
                yield event.plain_result(f"用法：{settings.decode_command} 乱码文本")
            else:
                yield event.plain_result(self._decode(payload, settings))
            event.stop_event()
            return

        alice_match = _match_command(text, settings.alice_command)
        if alice_match:
            yield event.plain_result(self._build_alice_reply(settings))
            event.stop_event()
            return

        help_match = _match_command(text, settings.help_command)
        if help_match:
            yield event.plain_result(self._help_text(settings))
            event.stop_event()
            return

        status_match = _match_command(text, settings.status_command)
        if status_match:
            yield event.plain_result(self._status_text(settings))
            event.stop_event()
            return

        if settings.trigger_enabled and self._matches_trigger(text, settings):
            if not self._trigger_on_cooldown(event, settings):
                yield event.plain_result(self._build_alice_reply(settings))
                if settings.trigger_stop_event:
                    event.stop_event()
            return

        if not settings.auto_decode_enabled:
            return
        if self._is_configured_command(text, settings):
            return
        if len(text) < settings.auto_decode_min_length:
            return

        result = decode_with_score(
            text,
            source_encoding=settings.source_encoding,
            wrong_encoding=settings.wrong_encoding,
            invalid_marker=settings.invalid_marker,
            unknown_chars=settings.unknown_chars,
            uncertain_char=settings.uncertain_char,
        )
        if not result.changed or result.score < settings.auto_decode_min_score:
            return

        decoded = result.text.strip()
        if not decoded or decoded == text:
            return

        logger.info(
            "[%s] auto decoded mojibake message, score=%s uncertain=%s",
            PLUGIN_ID,
            result.score,
            result.uncertain_count,
        )
        reply = self._render_template(
            settings.auto_decode_template,
            original=text,
            decoded=decoded,
            score=str(result.score),
            uncertain_count=str(result.uncertain_count),
        )
        yield event.plain_result(reply)
        if settings.auto_decode_stop_event:
            event.stop_event()

    async def terminate(self) -> None:
        logger.info("[%s] terminated", PLUGIN_ID)


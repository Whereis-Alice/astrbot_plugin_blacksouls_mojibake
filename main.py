from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from pydantic import Field
from pydantic.dataclasses import dataclass as pydantic_dataclass

from astrbot.api import AstrBotConfig, FunctionTool, logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.message_components import Plain
from astrbot.api.provider import LLMResponse
from astrbot.api.star import Context, Star, register
from astrbot.core.agent.run_context import ContextWrapper
from astrbot.core.agent.tool import ToolExecResult
from astrbot.core.astr_agent_context import AstrAgentContext

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
PLUGIN_VERSION = "0.2.0"
PLUGIN_DESC = "奈亚语转换工具：中文与 CP932/Shift-JIS 风格乱码互转，并支持爱丽丝里德尔触发后转换人格回复"
PLUGIN_REPO = "https://github.com/Whereis-Alice/astrbot_plugin_blacksouls_mojibake"

NYAYA_TRIGGER_EXTRA = "nyaya_alice_triggered"
DEFAULT_TOOL_DESCRIPTION = (
    "在用户明确要求把中文转换成奈亚语，或明确要求翻译/解读奈亚语乱码时使用。"
    "不要在用户只是闲聊、发送普通乱码梗、或没有提出转换需求时主动调用。"
)


@dataclass(frozen=True)
class PluginSettings:
    enabled: bool
    debug_log_conversions: bool
    debug_max_chars: int
    source_encoding: str
    wrong_encoding: str
    invalid_marker: str
    unknown_chars: str
    uncertain_char: str
    lossless_encode: bool
    tool_enabled: bool
    tool_name: str
    tool_description: str
    auto_mode_decode_min_score: int
    alice_enabled: bool
    alice_wake_llm: bool
    alice_trigger_phrases: list[str]
    alice_match_mode: str


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
        return [item for item in items if item] or default
    if isinstance(value, str):
        items = [
            item.strip()
            for item in value.replace("，", ",").replace("；", ";").split(";")
            for item in item.split(",")
        ]
        return [item for item in items if item] or default
    return default


def _safe_tool_name(value: str) -> str:
    name = re.sub(r"[^a-zA-Z0-9_]", "_", _clean_text(value, "convert_nyaya_language"))
    name = re.sub(r"_+", "_", name).strip("_")
    return name or "convert_nyaya_language"


@pydantic_dataclass
class NyayaLanguageTool(FunctionTool[AstrAgentContext]):
    name: str = "convert_nyaya_language"
    description: str = DEFAULT_TOOL_DESCRIPTION
    parameters: dict = Field(
        default_factory=lambda: {
            "type": "object",
            "properties": {
                "text": {
                    "type": "string",
                    "description": "需要转换的原文。可以是中文，也可以是奈亚语乱码。",
                },
                "mode": {
                    "type": "string",
                    "description": "转换方向。to_nyaya=中文转奈亚语；to_chinese=奈亚语转中文；auto=自动判断。",
                    "enum": ["to_nyaya", "to_chinese", "auto"],
                },
            },
            "required": ["text", "mode"],
        }
    )
    plugin: Any = Field(default=None)

    async def call(
        self,
        context: ContextWrapper[AstrAgentContext],
        **kwargs: Any,
    ) -> ToolExecResult:
        if self.plugin is None:
            return ToolExecResult(is_error=True, result="奈亚语工具未绑定插件实例。")
        return self.plugin.convert_for_tool(
            text=_clean_text(kwargs.get("text")),
            mode=_clean_text(kwargs.get("mode"), "auto"),
        )


@register(PLUGIN_ID, "Huli3", PLUGIN_DESC, PLUGIN_VERSION, PLUGIN_REPO)
class BlackSoulsMojibakePlugin(Star):
    """Nyaya language converter for BLACKSOULS-flavored mojibake."""

    def __init__(
        self,
        context: Context,
        config: AstrBotConfig | dict[str, Any] | None = None,
    ) -> None:
        super().__init__(context, config)
        self.config = config or {}
        self._tool: NyayaLanguageTool | None = None

        settings = self._settings()
        if settings.tool_enabled:
            self._tool = NyayaLanguageTool(
                name=settings.tool_name,
                description=settings.tool_description,
                plugin=self,
            )
            self.context.add_llm_tools(self._tool)

    async def initialize(self) -> None:
        logger.info("[%s] initialized", PLUGIN_ID)

    def _cfg(self, key: str, default: Any) -> Any:
        if hasattr(self.config, "get"):
            return self.config.get(key, default)
        return default

    def _section(self, key: str) -> dict[str, Any]:
        value = self._cfg(key, {})
        return value if isinstance(value, dict) else {}

    def _settings(self) -> PluginSettings:
        general = self._section("general")
        codec = self._section("codec")
        tool = self._section("llm_tool")
        alice = self._section("alice_trigger")

        match_mode = _clean_text(alice.get("match_mode"), "contains")
        if match_mode not in {"contains", "exact"}:
            match_mode = "contains"

        tool_name = _safe_tool_name(tool.get("name", "convert_nyaya_language"))
        tool_description = _clean_text(
            tool.get("description"),
            DEFAULT_TOOL_DESCRIPTION,
        )

        return PluginSettings(
            enabled=_read_bool(general.get("enabled"), True),
            debug_log_conversions=_read_bool(general.get("debug_log_conversions"), True),
            debug_max_chars=_read_int(
                general.get("debug_max_chars"),
                500,
                minimum=80,
                maximum=5000,
            ),
            source_encoding=_clean_text(
                codec.get("source_encoding"),
                DEFAULT_SOURCE_ENCODING,
            ),
            wrong_encoding=_clean_text(
                codec.get("wrong_encoding"),
                DEFAULT_WRONG_ENCODING,
            ),
            invalid_marker=_clean_text(
                codec.get("invalid_marker"),
                DEFAULT_INVALID_MARKER,
            ),
            unknown_chars=_clean_text(
                codec.get("unknown_chars"),
                DEFAULT_UNKNOWN_CHARS,
            ),
            uncertain_char=_clean_text(
                codec.get("uncertain_char"),
                DEFAULT_UNCERTAIN_CHAR,
            ),
            lossless_encode=_read_bool(codec.get("lossless_encode"), True),
            tool_enabled=_read_bool(tool.get("enabled"), True),
            tool_name=tool_name,
            tool_description=tool_description,
            auto_mode_decode_min_score=_read_int(
                tool.get("auto_mode_decode_min_score"),
                6,
                minimum=1,
                maximum=100,
            ),
            alice_enabled=_read_bool(alice.get("enabled"), True),
            alice_wake_llm=_read_bool(alice.get("wake_llm"), True),
            alice_trigger_phrases=_read_list(
                alice.get("trigger_phrases"),
                ["爱丽丝里德尔", "爱丽丝·里德尔"],
            ),
            alice_match_mode=match_mode,
        )

    def _truncate_for_log(self, text: str, settings: PluginSettings) -> str:
        text = text.replace("\r", "\\r").replace("\n", "\\n")
        if len(text) <= settings.debug_max_chars:
            return text
        return text[: settings.debug_max_chars - 3] + "..."

    def _log_conversion(
        self,
        *,
        settings: PluginSettings,
        source: str,
        direction: str,
        original: str,
        converted: str,
    ) -> None:
        if not settings.debug_log_conversions:
            return
        logger.debug(
            "[%s] %s conversion | direction=%s | original=%s | converted=%s",
            PLUGIN_ID,
            source,
            direction,
            self._truncate_for_log(original, settings),
            self._truncate_for_log(converted, settings),
        )

    def _encode(self, text: str, settings: PluginSettings) -> str:
        converted = encode_to_mojibake(
            text,
            source_encoding=settings.source_encoding,
            wrong_encoding=settings.wrong_encoding,
            invalid_marker=settings.invalid_marker,
            lossless=settings.lossless_encode,
        )
        return converted

    def _decode(self, text: str, settings: PluginSettings) -> str:
        converted = decode_from_mojibake(
            text,
            source_encoding=settings.source_encoding,
            wrong_encoding=settings.wrong_encoding,
            invalid_marker=settings.invalid_marker,
            unknown_chars=settings.unknown_chars,
            uncertain_char=settings.uncertain_char,
        )
        return converted

    def _normalize_tool_mode(self, mode: str) -> str:
        lowered = mode.strip().lower()
        aliases = {
            "to_nyaya": "to_nyaya",
            "nyaya": "to_nyaya",
            "encode": "to_nyaya",
            "garble": "to_nyaya",
            "中文转奈亚语": "to_nyaya",
            "转奈亚语": "to_nyaya",
            "to_chinese": "to_chinese",
            "decode": "to_chinese",
            "chinese": "to_chinese",
            "翻译": "to_chinese",
            "翻译奈亚语": "to_chinese",
            "奈亚语转中文": "to_chinese",
            "auto": "auto",
            "自动": "auto",
        }
        return aliases.get(lowered, "auto")

    def convert_for_tool(self, *, text: str, mode: str = "auto") -> ToolExecResult:
        settings = self._settings()
        if not settings.enabled:
            return ToolExecResult(is_error=True, result="奈亚语插件当前未启用。")
        if not settings.tool_enabled:
            return ToolExecResult(is_error=True, result="奈亚语 LLM 工具当前未启用。")
        if not text:
            return ToolExecResult(is_error=True, result="请提供需要转换的文本。")

        direction = self._normalize_tool_mode(mode)
        if direction == "auto":
            scored = decode_with_score(
                text,
                source_encoding=settings.source_encoding,
                wrong_encoding=settings.wrong_encoding,
                invalid_marker=settings.invalid_marker,
                unknown_chars=settings.unknown_chars,
                uncertain_char=settings.uncertain_char,
            )
            direction = (
                "to_chinese"
                if scored.score >= settings.auto_mode_decode_min_score and scored.changed
                else "to_nyaya"
            )

        if direction == "to_chinese":
            converted = self._decode(text, settings)
            label = "奈亚语转中文"
        else:
            converted = self._encode(text, settings)
            label = "中文转奈亚语"

        self._log_conversion(
            settings=settings,
            source="tool",
            direction=direction,
            original=text,
            converted=converted,
        )
        return ToolExecResult(result=f"{label}结果：\n{converted}")

    def _matches_alice_trigger(self, text: str, settings: PluginSettings) -> bool:
        normalized = text.strip()
        if not normalized:
            return False
        for phrase in settings.alice_trigger_phrases:
            if settings.alice_match_mode == "exact" and normalized == phrase:
                return True
            if settings.alice_match_mode == "contains" and phrase in normalized:
                return True
        return False

    @filter.event_message_type(filter.EventMessageType.ALL)
    async def mark_alice_trigger(self, event: AstrMessageEvent) -> None:
        settings = self._settings()
        if not settings.enabled or not settings.alice_enabled:
            return

        text = _clean_text(getattr(event, "message_str", ""))
        if not self._matches_alice_trigger(text, settings):
            return

        event.set_extra(NYAYA_TRIGGER_EXTRA, True)
        if settings.alice_wake_llm:
            event.is_at_or_wake_command = True
        logger.debug(
            "[%s] Alice Liddell trigger marked for session=%s wake_llm=%s",
            PLUGIN_ID,
            getattr(event, "unified_msg_origin", "unknown"),
            settings.alice_wake_llm,
        )

    def _convert_plain_chain_parts(
        self,
        response: LLMResponse,
        settings: PluginSettings,
    ) -> bool:
        chain = getattr(response, "result_chain", None)
        components = getattr(chain, "chain", None)
        if not isinstance(components, list):
            return False

        changed = False
        for component in components:
            if isinstance(component, Plain):
                original = component.text or ""
                component.text = self._encode(original, settings)
                changed = True
        return changed

    @filter.on_llm_response()
    async def convert_alice_response_to_nyaya(
        self,
        event: AstrMessageEvent,
        response: LLMResponse,
    ) -> None:
        settings = self._settings()
        if not settings.enabled or not settings.alice_enabled:
            return
        if not event.get_extra(NYAYA_TRIGGER_EXTRA, False):
            return

        original = _clean_text(getattr(response, "completion_text", ""))
        if not original:
            return

        converted = self._encode(original, settings)
        response.completion_text = converted

        if not self._convert_plain_chain_parts(response, settings):
            chain = getattr(response, "result_chain", None)
            if hasattr(chain, "chain"):
                chain.chain = [Plain(converted)]

        self._log_conversion(
            settings=settings,
            source="alice_response",
            direction="to_nyaya",
            original=original,
            converted=converted,
        )

    async def terminate(self) -> None:
        logger.info("[%s] terminated", PLUGIN_ID)

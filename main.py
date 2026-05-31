from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from pydantic import Field
from pydantic.dataclasses import dataclass as pydantic_dataclass

from astrbot.api import AstrBotConfig, FunctionTool, logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.message_components import Plain
from astrbot.api.provider import LLMResponse, ProviderRequest
from astrbot.api.star import Context, Star, register
from astrbot.core.agent.run_context import ContextWrapper
from astrbot.core.agent.tool import ToolExecResult
from astrbot.core.astr_agent_context import AstrAgentContext

try:
    from .codec import (
        DEFAULT_INVALID_MARKER,
        DEFAULT_LOSSLESS_STYLE,
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
        DEFAULT_LOSSLESS_STYLE,
        DEFAULT_SOURCE_ENCODING,
        DEFAULT_UNCERTAIN_CHAR,
        DEFAULT_UNKNOWN_CHARS,
        DEFAULT_WRONG_ENCODING,
        decode_from_mojibake,
        decode_with_score,
        encode_to_mojibake,
    )


PLUGIN_ID = "astrbot_plugin_blacksouls_mojibake"
PLUGIN_VERSION = "0.2.6"
PLUGIN_DESC = "奈亚语转换工具：中文与 CP932/Shift-JIS 风格乱码互转，并支持爱丽丝里德尔触发后转换人格回复"
PLUGIN_REPO = "https://github.com/Whereis-Alice/astrbot_plugin_blacksouls_mojibake"

NYAYA_TRIGGER_EXTRA = "nyaya_alice_triggered"
NYAYA_ALICE_ORIGINAL_MESSAGE_EXTRA = "nyaya_alice_original_message"
NYAYA_ALICE_PROMPT_EXTRA = "nyaya_alice_prompt"
NYAYA_TOOL_NAME = "convert_nyaya_language"
ALICE_EMPTY_PROMPT = "用户没有说其他内容，请按当前人格自然回应。"
DEFAULT_TOOL_REQUEST_KEYWORDS = [
    "奈亚语",
    "乱码",
    "转成",
    "转为",
    "转换",
    "翻译",
    "解读",
    "解释",
    "什么意思",
]
DEFAULT_TOOL_DESCRIPTION = (
    "奈亚语转换工具：convert_nyaya_language\n"
    "在用户明确要求把中文转换成奈亚语，或明确要求翻译/解读奈亚语乱码时使用。"
    "不要在用户只是闲聊、发送普通乱码梗、或没有提出转换需求时主动调用。"
    "\n调用时静默执行，不要说多余的话。"
)


@dataclass(frozen=True)
class PluginSettings:
    enabled: bool
    debug_log_conversions: bool
    debug_max_chars: int
    include_original_text: bool
    source_encoding: str
    wrong_encoding: str
    invalid_marker: str
    unknown_chars: str
    uncertain_char: str
    lossless_encode: bool
    lossless_style: str
    alice_lossless_encode: bool
    tool_enabled: bool
    tool_description: str
    inject_usage_hint: bool
    tool_request_keywords: list[str]
    auto_mode_decode_min_score: int
    commands_enabled: bool
    to_nyaya_command: str
    to_chinese_command: str
    help_command: str
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


def _split_command_aliases(value: str) -> list[str]:
    aliases: list[str] = []
    for alias in _read_list(value, []):
        aliases.append(alias)
        if alias[:1] in {"/", "!", "！"}:
            aliases.append(alias[1:])
    return list(dict.fromkeys(alias for alias in aliases if alias))


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


@pydantic_dataclass
class NyayaLanguageTool(FunctionTool[AstrAgentContext]):
    plugin: Any = Field(default=None, repr=False)
    name: str = NYAYA_TOOL_NAME
    description: str = DEFAULT_TOOL_DESCRIPTION
    parameters: dict[str, Any] = Field(
        default_factory=lambda: {
            "type": "object",
            "properties": {
                "text": {
                    "type": "string",
                    "description": "需要转换的文本。可以是中文，也可以是奈亚语乱码。",
                },
                "mode": {
                    "type": "string",
                    "description": "转换方向：to_nyaya、to_chinese 或 auto。",
                    "enum": ["to_nyaya", "to_chinese", "auto"],
                },
            },
            "required": ["text"],
        }
    )

    async def call(
        self,
        context: ContextWrapper[AstrAgentContext],
        **kwargs: Any,
    ) -> ToolExecResult:
        if self.plugin is None:
            return "奈亚语工具未绑定插件实例，请重载插件。"
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
        self._register_llm_tool()

    async def initialize(self) -> None:
        logger.info("[%s] initialized", PLUGIN_ID)

    def _register_llm_tool(self) -> None:
        settings = self._settings()
        self.context.add_llm_tools(
            NyayaLanguageTool(
                plugin=self,
                description=settings.tool_description,
                active=settings.enabled and settings.tool_enabled,
            )
        )

    def _cfg(self, key: str, default: Any) -> Any:
        if hasattr(self.config, "get"):
            return self.config.get(key, default)
        return default

    def _section(self, key: str) -> dict[str, Any]:
        value = self._cfg(key, {})
        return value if isinstance(value, dict) else {}

    def _settings(self) -> PluginSettings:
        general = self._section("general")
        display = self._section("display")
        codec = self._section("codec")
        tool = self._section("llm_tool")
        commands = self._section("commands")
        alice = self._section("alice_trigger")

        match_mode = _clean_text(alice.get("match_mode"), "contains")
        if match_mode not in {"contains", "exact"}:
            match_mode = "contains"

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
            include_original_text=_read_bool(display.get("include_original_text"), False),
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
            lossless_style=_clean_text(
                codec.get("lossless_style"),
                DEFAULT_LOSSLESS_STYLE,
            )
            if _clean_text(codec.get("lossless_style"), DEFAULT_LOSSLESS_STYLE) in {"visible", "hidden"}
            else DEFAULT_LOSSLESS_STYLE,
            alice_lossless_encode=_read_bool(alice.get("lossless_encode"), False),
            tool_enabled=_read_bool(tool.get("enabled"), True),
            tool_description=tool_description,
            inject_usage_hint=_read_bool(tool.get("inject_usage_hint"), True),
            tool_request_keywords=_read_list(
                tool.get("request_keywords"),
                DEFAULT_TOOL_REQUEST_KEYWORDS,
            ),
            auto_mode_decode_min_score=_read_int(
                tool.get("auto_mode_decode_min_score"),
                6,
                minimum=1,
                maximum=100,
            ),
            commands_enabled=_read_bool(commands.get("enabled"), True),
            to_nyaya_command=_clean_text(commands.get("to_nyaya"), "/nyaya,/奈亚语"),
            to_chinese_command=_clean_text(commands.get("to_chinese"), "/unyaya,/解奈亚语"),
            help_command=_clean_text(commands.get("help"), "/nyaya_help,/奈亚语帮助"),
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

    def _format_nyaya_reply(self, converted: str, original: str, settings: PluginSettings) -> str:
        if not settings.include_original_text:
            return converted
        return f"{converted}（{original}）"

    def _encode(
        self,
        text: str,
        settings: PluginSettings,
        *,
        lossless: bool | None = None,
    ) -> str:
        converted = encode_to_mojibake(
            text,
            source_encoding=settings.source_encoding,
            wrong_encoding=settings.wrong_encoding,
            invalid_marker=settings.invalid_marker,
            lossless=settings.lossless_encode if lossless is None else lossless,
            lossless_style=settings.lossless_style,
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

    def convert_for_tool(self, *, text: str, mode: str = "auto") -> str:
        settings = self._settings()
        if not settings.enabled:
            return "奈亚语插件当前未启用。"
        if not settings.tool_enabled:
            return "奈亚语 LLM 工具当前未启用。"
        if not text:
            return "请提供需要转换的文本。"

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
            final_text = converted
        else:
            converted = self._encode(text, settings)
            label = "中文转奈亚语"
            final_text = self._format_nyaya_reply(converted, text, settings)

        self._log_conversion(
            settings=settings,
            source="tool",
            direction=direction,
            original=text,
            converted=final_text,
        )
        return f"{label}结果：\n{final_text}"

    def _command_help_text(self, settings: PluginSettings) -> str:
        return (
            "奈亚语命令：\n"
            f"- 中文转奈亚语：{settings.to_nyaya_command} 文本\n"
            f"- 奈亚语转中文：{settings.to_chinese_command} 文本\n"
            f"- 帮助：{settings.help_command}\n\n"
            "也可以直接用自然语言要求 bot 转换，LLM 会调用奈亚语工具。"
        )

    def _message_requests_nyaya_tool(self, text: str, settings: PluginSettings) -> bool:
        return any(keyword and keyword in text for keyword in settings.tool_request_keywords)

    def _request_tool_names(self, request: ProviderRequest) -> list[str]:
        tool_set = getattr(request, "func_tool", None)
        if not tool_set:
            return []
        if hasattr(tool_set, "names"):
            return list(tool_set.names())
        return [getattr(tool, "name", "") for tool in getattr(tool_set, "tools", []) if getattr(tool, "name", "")]

    def _sync_nyaya_tool_description(
        self,
        request: ProviderRequest,
        settings: PluginSettings,
    ) -> bool:
        tool_set = getattr(request, "func_tool", None)
        if not tool_set or not hasattr(tool_set, "get_tool"):
            return False
        tool = tool_set.get_tool(NYAYA_TOOL_NAME)
        if not tool:
            return False
        tool.description = settings.tool_description
        return True

    def _strip_alice_trigger_text(self, text: str, settings: PluginSettings) -> str:
        normalized = text.strip()
        for phrase in sorted(settings.alice_trigger_phrases, key=len, reverse=True):
            if settings.alice_match_mode == "exact" and normalized == phrase:
                return ""
            if settings.alice_match_mode != "contains" or phrase not in normalized:
                continue
            stripped = normalized.replace(phrase, "", 1)
            return stripped.strip(" \t\r\n:：,，。.!！?？-—")
        return normalized

    def _hide_alice_phrases_in_text(self, text: str, settings: PluginSettings) -> tuple[str, bool]:
        cleaned = text
        for phrase in sorted(settings.alice_trigger_phrases, key=len, reverse=True):
            cleaned = cleaned.replace(phrase, "")
        if cleaned == text:
            return text, False
        cleaned = cleaned.strip(" \t\r\n:：,，。.!！?？-—")
        return cleaned or ALICE_EMPTY_PROMPT, True

    def _hide_alice_phrases_in_contexts(
        self,
        request: ProviderRequest,
        settings: PluginSettings,
    ) -> int:
        changed = 0
        for ctx in request.contexts or []:
            if not isinstance(ctx, dict) or ctx.get("role") != "user":
                continue
            content = ctx.get("content")
            if isinstance(content, str):
                cleaned, did_change = self._hide_alice_phrases_in_text(content, settings)
                if did_change:
                    ctx["content"] = cleaned
                    changed += 1
            elif isinstance(content, list):
                for part in content:
                    if not isinstance(part, dict) or part.get("type") != "text":
                        continue
                    cleaned, did_change = self._hide_alice_phrases_in_text(
                        str(part.get("text", "")),
                        settings,
                    )
                    if did_change:
                        part["text"] = cleaned
                        changed += 1
        return changed

    def _apply_alice_prompt_override(
        self,
        event: AstrMessageEvent,
        request: ProviderRequest,
        settings: PluginSettings,
    ) -> None:
        if not event.get_extra(NYAYA_TRIGGER_EXTRA, False):
            return

        original_prompt = _clean_text(getattr(request, "prompt", ""))
        visible_prompt = _clean_text(
            event.get_extra(NYAYA_ALICE_PROMPT_EXTRA, ""),
            ALICE_EMPTY_PROMPT,
        )
        request.prompt = visible_prompt
        changed_contexts = self._hide_alice_phrases_in_contexts(request, settings)
        logger.debug(
            "[%s] Alice trigger prompt hidden | original_prompt=%s | llm_prompt=%s | sanitized_contexts=%s",
            PLUGIN_ID,
            self._truncate_for_log(original_prompt, settings),
            self._truncate_for_log(visible_prompt, settings),
            changed_contexts,
        )

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

    @filter.event_message_type(filter.EventMessageType.ALL, priority=100)
    async def handle_message_triggers(self, event: AstrMessageEvent):
        settings = self._settings()
        if not settings.enabled:
            return

        text = _clean_text(getattr(event, "message_str", ""))

        if settings.commands_enabled:
            to_nyaya_match = _match_command(text, settings.to_nyaya_command)
            if to_nyaya_match:
                payload = to_nyaya_match[1]
                if not payload:
                    yield event.plain_result(f"用法：{settings.to_nyaya_command} 文本")
                else:
                    converted = self._encode(payload, settings)
                    final_text = self._format_nyaya_reply(converted, payload, settings)
                    self._log_conversion(
                        settings=settings,
                        source="command",
                        direction="to_nyaya",
                        original=payload,
                        converted=final_text,
                    )
                    yield event.plain_result(final_text)
                event.stop_event()
                return

            to_chinese_match = _match_command(text, settings.to_chinese_command)
            if to_chinese_match:
                payload = to_chinese_match[1]
                if not payload:
                    yield event.plain_result(f"用法：{settings.to_chinese_command} 文本")
                else:
                    converted = self._decode(payload, settings)
                    self._log_conversion(
                        settings=settings,
                        source="command",
                        direction="to_chinese",
                        original=payload,
                        converted=converted,
                    )
                    yield event.plain_result(converted)
                event.stop_event()
                return

            help_match = _match_command(text, settings.help_command)
            if help_match:
                yield event.plain_result(self._command_help_text(settings))
                event.stop_event()
                return

        if not settings.alice_enabled:
            return
        if not self._matches_alice_trigger(text, settings):
            return

        visible_prompt = self._strip_alice_trigger_text(text, settings)
        event.set_extra(NYAYA_TRIGGER_EXTRA, True)
        event.set_extra(NYAYA_ALICE_ORIGINAL_MESSAGE_EXTRA, text)
        event.set_extra(NYAYA_ALICE_PROMPT_EXTRA, visible_prompt)
        event.message_str = visible_prompt or ALICE_EMPTY_PROMPT
        if settings.alice_wake_llm:
            event.is_at_or_wake_command = True
        logger.debug(
            "[%s] Alice Liddell trigger marked for session=%s wake_llm=%s llm_prompt=%s",
            PLUGIN_ID,
            getattr(event, "unified_msg_origin", "unknown"),
            settings.alice_wake_llm,
            self._truncate_for_log(visible_prompt or ALICE_EMPTY_PROMPT, settings),
        )

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

        converted = self._encode(
            original,
            settings,
            lossless=settings.alice_lossless_encode,
        )
        final_text = self._format_nyaya_reply(converted, original, settings)
        response.completion_text = final_text

        chain = getattr(response, "result_chain", None)
        if hasattr(chain, "chain"):
            chain.chain = [Plain(final_text)]

        self._log_conversion(
            settings=settings,
            source="alice_response",
            direction="to_nyaya",
            original=original,
            converted=final_text,
        )

    @filter.on_llm_request()
    async def inject_nyaya_tool_hint(
        self,
        event: AstrMessageEvent,
        request: ProviderRequest,
    ) -> None:
        settings = self._settings()
        if not settings.enabled:
            return

        self._apply_alice_prompt_override(event, request, settings)

        if not settings.tool_enabled or not settings.inject_usage_hint:
            return

        has_nyaya_tool = self._sync_nyaya_tool_description(request, settings)
        message = _clean_text(getattr(event, "message_str", ""))
        if not self._message_requests_nyaya_tool(message, settings):
            return

        hint = (
            "\n\n[奈亚语工具提示]\n"
            "如果用户明确要求转换、翻译或解读奈亚语/乱码，请调用 "
            f"`{NYAYA_TOOL_NAME}` 工具，不要写 Python 或导入插件源码自行处理。"
            "如果用户引用了一段消息，请把引用里的奈亚语原文作为 text；解读/翻译时 mode 用 to_chinese，"
            "中文转奈亚语时 mode 用 to_nyaya，不确定时 mode 用 auto。"
        )
        if hint not in request.system_prompt:
            request.system_prompt = f"{request.system_prompt}{hint}" if request.system_prompt else hint.strip()

        logger.debug(
            "[%s] nyaya LLM hint injected | has_tool=%s | tools=%s | message=%s",
            PLUGIN_ID,
            has_nyaya_tool,
            self._request_tool_names(request),
            self._truncate_for_log(message, settings),
        )

    async def terminate(self) -> None:
        logger.info("[%s] terminated", PLUGIN_ID)

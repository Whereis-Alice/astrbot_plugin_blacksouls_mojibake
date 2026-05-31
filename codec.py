from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable


DEFAULT_WRONG_ENCODING = "cp932"
DEFAULT_SOURCE_ENCODING = "utf-8"
DEFAULT_INVALID_MARKER = "・"
DEFAULT_UNKNOWN_CHARS = "・?"
DEFAULT_UNCERTAIN_CHAR = "□"
DEFAULT_LOSSLESS_STYLE = "hidden"

HIDDEN_BYTE_PREFIX = "\u2060"
HIDDEN_ZERO = "\u200b"
HIDDEN_ONE = "\u200c"
VARIATION_SELECTOR_START = 0xFE00
VARIATION_SELECTOR_SUPPLEMENT_START = 0xE0100
TAG_NIBBLE_START = 0xE0030

_HEX_PAIR_RE = re.compile(r"^[0-9a-fA-F]{2}$")

_CP932_LEAD_RANGES = ((0x81, 0x9F), (0xE0, 0xFC))
_READABLE_PUNCTUATION = set(
    " \n\r\t,，.。!！?？:：;；、-—_()（）[]【】{}《》<>“”‘’'\"/\\|~～…·"
)

_CONTEXT_PRIORITY = {
    "爱丽": "丝",
    "愛麗": "絲",
    "被知": "道",
    "被確": "定認",
    "被确": "定认",
    "被理": "解",
}

_CANDIDATE_PRIORITY = (
    "的了不一是在人有和中为以到说要就这也子个"
    "道定認认解理發发现現覺觉確确識识知找看察到"
    "丝絲么什吗嗎呢吧啊笑温柔冷梦夢希望世界朋友"
)

_MOJIBAKE_SIGNATURES = set(
    "荳蜿逧譌蟆霑陲逋迴謇蛻遏驕遒螳隱隕蟇蜈"
    "縺繧謔諢豁譁蜃蛹螟逵螯莉荵蝨譛闌"
)


@dataclass(frozen=True)
class DecodeResult:
    text: str
    score: int
    changed: bool
    uncertain_count: int


def _normalize_encoding(name: str) -> str:
    normalized = (name or DEFAULT_WRONG_ENCODING).strip().lower().replace("-", "_")
    if normalized in {"sjis", "shift_jis", "shiftjis", "windows_31j", "ms932"}:
        return "cp932"
    return normalized or DEFAULT_WRONG_ENCODING


def _is_cp932_lead(byte: int) -> bool:
    return any(start <= byte <= end for start, end in _CP932_LEAD_RANGES)


def _decode_cp932_bytes_lossless(
    data: bytes,
    *,
    invalid_marker: str = DEFAULT_INVALID_MARKER,
    lossless: bool = True,
    lossless_style: str = DEFAULT_LOSSLESS_STYLE,
) -> str:
    marker = invalid_marker or DEFAULT_INVALID_MARKER
    style = (
        lossless_style
        if lossless_style in {"visible", "hidden", "zero_width"}
        else DEFAULT_LOSSLESS_STYLE
    )
    output: list[str] = []
    index = 0
    while index < len(data):
        byte = data[index]

        if _is_cp932_lead(byte) and index + 1 < len(data):
            chunk = data[index : index + 2]
            try:
                output.append(chunk.decode("cp932", errors="strict"))
                index += 2
                continue
            except UnicodeDecodeError:
                pass

        try:
            output.append(bytes([byte]).decode("cp932", errors="strict"))
        except UnicodeDecodeError:
            if lossless:
                if style == "visible":
                    output.append(f"{marker}{byte:02X}")
                elif style == "zero_width":
                    output.append(f"{marker}{_encode_zero_width_byte(byte)}")
                else:
                    output.append(f"{marker}{_encode_tag_byte(byte)}")
            else:
                output.append(marker)
        index += 1

    return "".join(output)


def encode_to_mojibake(
    text: str,
    *,
    source_encoding: str = DEFAULT_SOURCE_ENCODING,
    wrong_encoding: str = DEFAULT_WRONG_ENCODING,
    invalid_marker: str = DEFAULT_INVALID_MARKER,
    lossless: bool = True,
    lossless_style: str = DEFAULT_LOSSLESS_STYLE,
) -> str:
    """Encode readable text into CP932-style mojibake.

    In lossless mode invalid CP932 bytes are emitted as marker+hex, e.g. "・84".
    That keeps the BLACKSOULS flavor while making command round-trips exact.
    """

    if not text:
        return ""

    source_encoding = source_encoding or DEFAULT_SOURCE_ENCODING
    wrong_encoding = _normalize_encoding(wrong_encoding)
    data = text.encode(source_encoding, errors="strict")

    if wrong_encoding == "cp932":
        return _decode_cp932_bytes_lossless(
            data,
            invalid_marker=invalid_marker,
            lossless=lossless,
            lossless_style=lossless_style,
        )

    return data.decode(wrong_encoding, errors="replace")


def _append_encoded_char(
    stream: list[int | None],
    char: str,
    *,
    wrong_encoding: str,
    unknown_chars: set[str],
) -> None:
    if char in unknown_chars:
        stream.append(None)
        return

    try:
        stream.extend(char.encode(wrong_encoding, errors="strict"))
    except UnicodeEncodeError:
        stream.append(None)


def _encode_tag_byte(byte: int) -> str:
    return chr(TAG_NIBBLE_START + (byte >> 4)) + chr(TAG_NIBBLE_START + (byte & 0x0F))


def _try_decode_tag_byte(text: str, start: int) -> tuple[int, int] | None:
    if start + 1 >= len(text):
        return None
    high = ord(text[start])
    low = ord(text[start + 1])
    if (
        TAG_NIBBLE_START <= high <= TAG_NIBBLE_START + 15
        and TAG_NIBBLE_START <= low <= TAG_NIBBLE_START + 15
    ):
        return ((high - TAG_NIBBLE_START) << 4) | (low - TAG_NIBBLE_START), start + 2
    return None


def _encode_variation_byte(byte: int) -> str:
    return chr(VARIATION_SELECTOR_START + (byte >> 4)) + chr(VARIATION_SELECTOR_START + (byte & 0x0F))


def _try_decode_variation_byte(text: str, start: int) -> tuple[int, int] | None:
    if start >= len(text):
        return None

    if start + 1 < len(text):
        high = ord(text[start])
        low = ord(text[start + 1])
        if (
            VARIATION_SELECTOR_START <= high <= VARIATION_SELECTOR_START + 15
            and VARIATION_SELECTOR_START <= low <= VARIATION_SELECTOR_START + 15
        ):
            return ((high - VARIATION_SELECTOR_START) << 4) | (low - VARIATION_SELECTOR_START), start + 2

    codepoint = ord(text[start])
    if VARIATION_SELECTOR_START <= codepoint <= VARIATION_SELECTOR_START + 15:
        return codepoint - VARIATION_SELECTOR_START, start + 1
    if VARIATION_SELECTOR_SUPPLEMENT_START <= codepoint <= VARIATION_SELECTOR_SUPPLEMENT_START + 239:
        return codepoint - VARIATION_SELECTOR_SUPPLEMENT_START + 16, start + 1
    return None


def _encode_zero_width_byte(byte: int) -> str:
    bits = "".join(HIDDEN_ONE if byte & (1 << shift) else HIDDEN_ZERO for shift in range(7, -1, -1))
    return HIDDEN_BYTE_PREFIX + bits


def _try_decode_zero_width_byte(text: str, start: int) -> tuple[int, int] | None:
    if start >= len(text) or text[start] != HIDDEN_BYTE_PREFIX:
        return None
    bit_start = start + 1
    bit_end = bit_start + 8
    bits = text[bit_start:bit_end]
    if len(bits) != 8:
        return None
    value = 0
    for char in bits:
        if char == HIDDEN_ZERO:
            value = value << 1
        elif char == HIDDEN_ONE:
            value = (value << 1) | 1
        else:
            return None
    return value, bit_end


def mojibake_to_byte_stream(
    text: str,
    *,
    wrong_encoding: str = DEFAULT_WRONG_ENCODING,
    invalid_marker: str = DEFAULT_INVALID_MARKER,
    unknown_chars: str = DEFAULT_UNKNOWN_CHARS,
) -> list[int | None]:
    wrong_encoding = _normalize_encoding(wrong_encoding)
    marker = invalid_marker or DEFAULT_INVALID_MARKER
    unknown_set = set(unknown_chars or "")
    stream: list[int | None] = []

    index = 0
    while index < len(text):
        if marker and text.startswith(marker, index):
            payload_start = index + len(marker)
            tag = _try_decode_tag_byte(text, payload_start)
            if tag is not None:
                byte, next_index = tag
                stream.append(byte)
                index = next_index
                continue

            variation = _try_decode_variation_byte(text, payload_start)
            if variation is not None:
                byte, next_index = variation
                stream.append(byte)
                index = next_index
                continue

            hidden = _try_decode_zero_width_byte(text, payload_start)
            if hidden is not None:
                byte, next_index = hidden
                stream.append(byte)
                index = next_index
                continue

            hex_start = payload_start
            hex_pair = text[hex_start : hex_start + 2]
            if len(hex_pair) == 2 and _HEX_PAIR_RE.match(hex_pair):
                stream.append(int(hex_pair, 16))
                index = hex_start + 2
                continue

        char = text[index]
        _append_encoded_char(
            stream,
            char,
            wrong_encoding=wrong_encoding,
            unknown_chars=unknown_set,
        )
        index += 1

    return stream


def _utf8_sequence_length(first_byte: int | None) -> int:
    if first_byte is None:
        return 1
    if first_byte < 0x80:
        return 1
    if 0xC2 <= first_byte <= 0xDF:
        return 2
    if 0xE0 <= first_byte <= 0xEF:
        return 3
    if 0xF0 <= first_byte <= 0xF4:
        return 4
    return 1


def _is_readable_candidate(char: str) -> bool:
    if not char:
        return False
    if char in _READABLE_PUNCTUATION:
        return True
    codepoint = ord(char)
    return (
        0x4E00 <= codepoint <= 0x9FFF
        or 0x3400 <= codepoint <= 0x4DBF
        or 0x3000 <= codepoint <= 0x303F
        or 0xFF00 <= codepoint <= 0xFFEF
    )


def _candidate_texts(sequence: list[int | None]) -> list[str]:
    unknown_positions = [index for index, byte in enumerate(sequence) if byte is None]
    if not unknown_positions:
        try:
            return [bytes(sequence).decode("utf-8")]  # type: ignore[arg-type]
        except UnicodeDecodeError:
            return []

    candidates: list[str] = []

    def walk(position: int, current: list[int | None]) -> None:
        if position >= len(unknown_positions):
            try:
                decoded = bytes(current).decode("utf-8")  # type: ignore[arg-type]
            except UnicodeDecodeError:
                return
            if len(decoded) == 1 and _is_readable_candidate(decoded):
                candidates.append(decoded)
            return

        target = unknown_positions[position]
        for value in range(0x80, 0xC0):
            current[target] = value
            walk(position + 1, current)
        current[target] = None

    walk(0, list(sequence))
    return candidates


def _choose_candidate(candidates: Iterable[str], current_text: str, uncertain_char: str) -> str:
    unique = list(dict.fromkeys(candidates))
    if not unique:
        return uncertain_char
    if len(unique) == 1:
        return unique[0]

    for context, chars in _CONTEXT_PRIORITY.items():
        if current_text.endswith(context):
            for char in chars:
                if char in unique:
                    return char

    for char in _CANDIDATE_PRIORITY:
        if char in unique:
            return char

    return unique[0] if _is_readable_candidate(unique[0]) else uncertain_char


def _decode_utf8_stream_with_unknowns(
    stream: list[int | None],
    *,
    uncertain_char: str = DEFAULT_UNCERTAIN_CHAR,
) -> str:
    output: list[str] = []
    index = 0
    while index < len(stream):
        first = stream[index]
        length = _utf8_sequence_length(first)
        sequence = stream[index : index + length]
        if len(sequence) < length:
            output.append(uncertain_char)
            break

        if length == 1:
            if first is None:
                output.append(uncertain_char)
            elif first < 0x80:
                output.append(chr(first))
            else:
                output.append(uncertain_char)
            index += 1
            continue

        candidates = _candidate_texts(sequence)
        output.append(_choose_candidate(candidates, "".join(output), uncertain_char))
        index += length

    return "".join(output)


def _polish_common_fragments(text: str, uncertain_char: str) -> str:
    box = re.escape(uncertain_char)
    replacements = {
        f"被理{uncertain_char}{uncertain_char}": "被理解",
        f"知{uncertain_char}": "知道",
        f"確{uncertain_char}": "確定",
        f"确{uncertain_char}": "确定",
    }
    polished = text
    for old, new in replacements.items():
        polished = polished.replace(old, new)

    polished = re.sub(rf"爱丽{box}", "爱丽丝", polished)
    polished = re.sub(rf"愛麗{box}", "愛麗絲", polished)
    return polished


def decode_from_mojibake(
    text: str,
    *,
    source_encoding: str = DEFAULT_SOURCE_ENCODING,
    wrong_encoding: str = DEFAULT_WRONG_ENCODING,
    invalid_marker: str = DEFAULT_INVALID_MARKER,
    unknown_chars: str = DEFAULT_UNKNOWN_CHARS,
    uncertain_char: str = DEFAULT_UNCERTAIN_CHAR,
) -> str:
    if not text:
        return ""

    source_encoding = source_encoding or DEFAULT_SOURCE_ENCODING
    wrong_encoding = _normalize_encoding(wrong_encoding)

    if source_encoding.lower().replace("-", "_") != "utf_8":
        try:
            data = bytes(
                byte if byte is not None else ord("?")
                for byte in mojibake_to_byte_stream(
                    text,
                    wrong_encoding=wrong_encoding,
                    invalid_marker=invalid_marker,
                    unknown_chars=unknown_chars,
                )
            )
            return data.decode(source_encoding, errors="replace")
        except Exception:
            return text

    stream = mojibake_to_byte_stream(
        text,
        wrong_encoding=wrong_encoding,
        invalid_marker=invalid_marker,
        unknown_chars=unknown_chars,
    )
    decoded = _decode_utf8_stream_with_unknowns(stream, uncertain_char=uncertain_char)
    return _polish_common_fragments(decoded, uncertain_char)


def mojibake_score(
    text: str,
    *,
    invalid_marker: str = DEFAULT_INVALID_MARKER,
    marker_counts_as: int = 2,
) -> int:
    if not text:
        return 0

    score = 0
    marker = invalid_marker or DEFAULT_INVALID_MARKER
    index = 0
    while index < len(text):
        char = text[index]
        codepoint = ord(char)
        if 0xFF61 <= codepoint <= 0xFF9F:
            score += 2
        elif char in _MOJIBAKE_SIGNATURES:
            score += 1
        elif char == "\uf8f0" or codepoint < 0x20 and char not in "\n\r\t":
            score += 2
        elif marker and text.startswith(marker, index):
            score += marker_counts_as
        index += 1

    return score


def decode_with_score(
    text: str,
    *,
    source_encoding: str = DEFAULT_SOURCE_ENCODING,
    wrong_encoding: str = DEFAULT_WRONG_ENCODING,
    invalid_marker: str = DEFAULT_INVALID_MARKER,
    unknown_chars: str = DEFAULT_UNKNOWN_CHARS,
    uncertain_char: str = DEFAULT_UNCERTAIN_CHAR,
) -> DecodeResult:
    decoded = decode_from_mojibake(
        text,
        source_encoding=source_encoding,
        wrong_encoding=wrong_encoding,
        invalid_marker=invalid_marker,
        unknown_chars=unknown_chars,
        uncertain_char=uncertain_char,
    )
    return DecodeResult(
        text=decoded,
        score=mojibake_score(text, invalid_marker=invalid_marker),
        changed=decoded != text,
        uncertain_count=decoded.count(uncertain_char),
    )

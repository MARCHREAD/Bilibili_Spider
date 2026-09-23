"""极简 protobuf wire-format 解析器（无第三方依赖）。

只做 wire 层（varint / 64bit / length-delimited / 32bit）递归展开，
不做 schema 映射 —— 因为弹幕下发的是**二进制编码**而非加密，
`.proto` 只需按字段号对照即可。
"""

from __future__ import annotations

from typing import Any

WIRE_VARINT = 0
WIRE_64 = 1
WIRE_LEN = 2
WIRE_32 = 5


def read_varint(buf: bytes, pos: int) -> tuple[int, int]:
    result = 0
    shift = 0
    while True:
        if pos >= len(buf):
            raise ValueError("varint 越界")
        byte = buf[pos]
        pos += 1
        result |= (byte & 0x7F) << shift
        if not byte & 0x80:
            return result, pos
        shift += 7
        if shift > 63:
            raise ValueError("varint 过长")


def _looks_text(raw: bytes) -> bool:
    if not raw:
        return False
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        return False
    return all(ch.isprintable() or ch in "\r\n\t" for ch in text)


def _decode_value(raw: bytes, depth: int) -> Any:
    """length-delimited 字段：能当文本就当文本，否则尝试嵌套消息。"""
    if _looks_text(raw):
        return raw.decode("utf-8")
    if depth <= 0 or len(raw) < 2:
        return {"_bytes": raw.hex()}
    try:
        nested = parse(raw, depth - 1)
    except Exception:
        return {"_bytes": raw.hex()}
    if not nested:
        return {"_bytes": raw.hex()}
    return {"_msg": nested}


def parse(buf: bytes, depth: int = 3) -> dict[int, list[Any]]:
    """展开一层消息，返回 {字段号: [值, ...]}。"""
    fields: dict[int, list[Any]] = {}
    pos = 0
    size = len(buf)
    while pos < size:
        key, pos = read_varint(buf, pos)
        field_no = key >> 3
        wire = key & 0x07
        if field_no == 0:
            raise ValueError("字段号为 0，非法")
        if wire == WIRE_VARINT:
            value, pos = read_varint(buf, pos)
        elif wire == WIRE_64:
            value = int.from_bytes(buf[pos:pos + 8], "little")
            pos += 8
        elif wire == WIRE_LEN:
            length, pos = read_varint(buf, pos)
            raw = buf[pos:pos + length]
            if len(raw) != length:
                raise ValueError("length-delimited 越界")
            pos += length
            value = _decode_value(raw, depth)
        elif wire == WIRE_32:
            value = int.from_bytes(buf[pos:pos + 4], "little")
            pos += 4
        else:
            raise ValueError(f"未知 wire type {wire}")
        fields.setdefault(field_no, []).append(value)
    return fields


def scalar(fields: dict, no: int, default: Any = None) -> Any:
    values = fields.get(no)
    return values[0] if values else default


def scalars(fields: dict, no: int) -> list:
    return list(fields.get(no) or [])

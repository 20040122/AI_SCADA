from __future__ import annotations

import csv
import io

MAX_CSV_BYTES = 5 * 1024 * 1024
MAX_CSV_ROWS = 10000

EXPECTED_HEADER = ["displayName", "propertyName"]


class CsvError(Exception):
    pass


class CsvEncodingError(CsvError):
    pass


class CsvTooLargeError(CsvError):
    pass


class CsvTooManyRowsError(CsvError):
    pass


def detect_encoding(data: bytes) -> str:
    if data.startswith(b"\xef\xbb\xbf"):
        return "utf-8-sig"
    for enc in ("utf-8", "gb18030"):
        try:
            data.decode(enc)
            return enc
        except UnicodeDecodeError:
            continue
    raise CsvEncodingError("无法识别的编码，仅支持 UTF-8 / GB18030")


def _parse(data: bytes) -> tuple[str, list[tuple[int, list[str]]]]:
    if len(data) > MAX_CSV_BYTES:
        raise CsvTooLargeError("CSV 超过 5MB 限制")
    encoding = detect_encoding(data)
    text = data.decode(encoding)
    if text == "":
        raise CsvError("CSV 为空")
    reader = csv.reader(io.StringIO(text))
    records: list[tuple[int, list[str]]] = []
    prev_line = 0
    for record in reader:
        start_line = prev_line + 1
        prev_line = reader.line_num
        if not any(cell.strip() for cell in record):
            continue
        records.append((start_line, [cell.strip() for cell in record]))
    if not records:
        raise CsvError("CSV 为空")
    return encoding, records


def preview_csv(data: bytes) -> dict:
    encoding, records = _parse(data)
    _, header = records[0]
    if header != EXPECTED_HEADER:
        raise CsvError(
            f"表头必须精确为 {EXPECTED_HEADER[0]},{EXPECTED_HEADER[1]}，实际为: {','.join(header)}"
        )
    data_records = records[1:]
    if len(data_records) > MAX_CSV_ROWS:
        raise CsvTooManyRowsError(f"CSV 数据行超过 {MAX_CSV_ROWS} 行限制")
    requests: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for line, row in data_records:
        if len(row) != 2:
            raise CsvError(f"第 {line} 行: 必须恰好 2 列，实际 {len(row)} 列")
        display_name, property_name = row
        if not display_name or not property_name:
            raise CsvError(f"第 {line} 行: displayName 和 propertyName 均不能为空")
        key = (display_name, property_name)
        if key in seen:
            raise CsvError(f"第 {line} 行: 重复的 displayName+propertyName 组合")
        seen.add(key)
        requests.append({
            "row_number": line,
            "displayName": display_name,
            "propertyName": property_name,
        })
    return {"encoding": encoding, "total_rows": len(requests), "requests": requests}

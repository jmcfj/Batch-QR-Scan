"""Keep printed labels separate from authoritative table names."""
import csv
import re
import unicodedata
import json
from pathlib import Path
from functools import lru_cache
from urllib.parse import urlsplit, parse_qs


def normalize_label(value):
    return unicodedata.normalize('NFKC', value).strip().upper()


def comparison_key(value):
    """Case-insensitive table identity; keep raw display values untouched."""
    return re.sub(r'[0-9]+', lambda m: m[0].lstrip('0') or '0', normalize_label(value))


def heading_label(text):
    value = normalize_label(text)
    if any(word in value for word in ('密码', '账号', '帐号', 'WIFI', 'WIF1', 'W1FI', 'W1F1')):
        return ''
    match = re.match(r'^([A-Z]{1,4}\s*\d{1,4})(?!\d)', value)
    return re.sub(r'\s+', '', match[1]) if match else ''


@lru_cache(maxsize=1)
def ocr_engine():
    from rapidocr_onnxruntime import RapidOCR
    return RapidOCR(intra_op_num_threads=2, inter_op_num_threads=2)


def printed_labels(image):
    import numpy as np
    factor = min(2, 3600 / max(image.size))
    resized = image.resize((round(image.width * factor), round(image.height * factor)))
    found, _ = ocr_engine()(np.asarray(resized))
    labels = []
    for box, text, score in found or []:
        # Restrict automatic label detection; never interpret the Wi-Fi password.
        label = heading_label(text)
        if not label or score < .85:
            continue
        labels.append((min(p[0] for p in box) / factor,
                       min(p[1] for p in box) / factor,
                       max(p[0] for p in box) / factor,
                       max(p[1] for p in box) / factor,
                       label))
    return labels


def label_for(bounds, labels):
    x0, y0, x1, y1 = bounds
    width, height = x1 - x0, y1 - y0
    cx = (x0 + x1) / 2
    candidates = [label for label in labels
                  if x0 - width * .5 <= (label[0] + label[2]) / 2 <= x1 + width * .5
                  and y0 - height * .9 <= label[3] <= y0 + height * .05]
    candidates.sort(key=lambda label: abs(cx - (label[0] + label[2]) / 2) + abs(y0 - label[3]))
    if len(candidates) > 1:
        return ''  # Ambiguous headings require human review.
    return candidates[0][4] if candidates else ''


def url_table_info(text):
    try:
        params = parse_qs(urlsplit(text).query)
    except ValueError:
        return '', ''
    internal_id = next((params[k][0] for k in ('dId', 'tableId', 'deskId', 'table_id') if k in params), '')
    # Only explicitly named, unambiguous table-name parameters qualify.
    names = {comparison_key(v): v.strip() for k in ('tableName', 'deskName', 'table_name', 'desk_name')
             for v in params.get(k, []) if v.strip()}
    return internal_id, next(iter(names.values())) if len(names) == 1 else ''


def apply_reference(row, reference, evidence='独立对照清单'):
    if row.live_status:
        if row.live_status != '已读取':
            row.actual_table = ''
            row.table_evidence = ''
        compare_table(row)
        return
    row.table_id, param_name = url_table_info(row.text)
    row.actual_table = reference.get(row.text.strip(), '') or param_name
    row.table_evidence = evidence if row.text.strip() in reference else ('链接台号参数' if param_name else '')
    compare_table(row)


def compare_table(row):
    if row.status != '已识别':
        row.table_check = '无法核对'
    elif not row.actual_table:
        row.table_check = '待核实：缺少实际台号'
    elif not row.printed_table:
        row.table_check = '待核实：未读到印刷台号'
    elif comparison_key(row.printed_table) == comparison_key(row.actual_table):
        row.table_check = '一致'
    else:
        row.table_check = '不一致'


def load_reference(path):
    with open(path, encoding='utf-8-sig', newline='') as stream:
        reader = csv.DictReader(stream)
        if not {'url', 'actual_table'}.issubset(reader.fieldnames or []):
            raise ValueError('CSV 必须有 url 和 actual_table 两列；请使用独立的后台或微信核实数据。')
        reference = {}
        for index, row in enumerate(reader, 2):
            url, name = (row.get('url') or '').strip(), (row.get('actual_table') or '').strip()
            if not url or not name:
                raise ValueError(f'第 {index} 行缺少网址或实际台号')
            if url in reference and comparison_key(reference[url]) != comparison_key(name):
                raise ValueError(f'第 {index} 行同一个网址对应多个台号')
            reference[url] = name
    if not reference:
        raise ValueError('对照清单为空')
    return reference


def load_reference_folder(folder):
    """Backend export: one barcode per file, authoritative table name in filename.

    Exact payload matching keeps merchant identity and every URL parameter intact.
    Reject the whole import on unreadable/ambiguous/conflicting entries.
    """
    from scanner import SUPPORTED, scan_file
    root = Path(folder)
    if not root.is_dir():
        raise ValueError('原始码文件夹不存在')
    reference = {}
    for path in sorted(root.rglob('*')):
        if not path.is_file() or path.suffix.lower() not in SUPPORTED:
            continue
        rows = [r for page in scan_file(path) for r in page]
        if len(rows) != 1 or rows[0].status != '已识别':
            raise ValueError(f'{path.name}：每个后台原码文件必须只包含一个可识别的码，请排除排版图或损坏文件。')
        text, name = rows[0].text.strip(), path.stem.strip()
        if not text or not name:
            raise ValueError(f'{path.name}：缺少内容或台号文件名')
        if text in reference and comparison_key(reference[text]) != comparison_key(name):
            raise ValueError(f'原码冲突：同一个码同时命名为 {reference[text]} 和 {name}，请先核实后台原始文件。')
        reference[text] = name
    if not reference:
        raise ValueError('文件夹中没有可识别的后台原码图片或 PDF')
    return reference


def save_reference_state(path, reference, evidence):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps({'reference': reference, 'evidence': evidence}, ensure_ascii=False, indent=2), encoding='utf-8')
    temporary.replace(path)


def read_reference_state(path):
    try:
        data = json.loads(Path(path).read_text(encoding='utf-8'))
        reference, evidence = data['reference'], data['evidence']
        if not isinstance(reference, dict) or not isinstance(evidence, str):
            raise ValueError('Invalid reference data')
        if not all(isinstance(k, str) and isinstance(v, str) and k and v for k, v in reference.items()):
            raise ValueError('Invalid table names')
        return reference, evidence
    except (OSError, ValueError, KeyError, TypeError):
        return {}, '独立对照清单'

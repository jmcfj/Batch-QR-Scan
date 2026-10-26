"""Keep printed labels separate from authoritative table names."""
import csv
import re
import unicodedata
from functools import lru_cache
from urllib.parse import urlsplit, parse_qs


def normalize_label(value):
    return unicodedata.normalize('NFKC', value).strip().upper()


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
        match = re.match(r'^([A-Za-z]{1,4}\s*\d{1,4})(?!\d)', normalize_label(text))
        if not match or score < .85:
            continue
        labels.append((min(p[0] for p in box) / factor,
                       min(p[1] for p in box) / factor,
                       max(p[0] for p in box) / factor,
                       max(p[1] for p in box) / factor,
                       re.sub(r'\s+', '', match[1])))
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
    names = {normalize_label(v) for k in ('tableName', 'deskName', 'table_name', 'desk_name')
             for v in params.get(k, []) if v.strip()}
    return internal_id, next(iter(names)) if len(names) == 1 else ''


def apply_reference(row, reference):
    row.table_id, param_name = url_table_info(row.text)
    row.actual_table = reference.get(row.text.strip(), '') or param_name
    row.table_evidence = '独立对照清单' if row.text.strip() in reference else ('链接台号参数' if param_name else '')
    if row.status != '已识别':
        row.table_check = '无法核对'
    elif not row.actual_table:
        row.table_check = '待核实：缺少实际台号'
    elif not row.printed_table:
        row.table_check = '待核实：未读到印刷台号'
    elif normalize_label(row.printed_table) == normalize_label(row.actual_table):
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
            if url in reference and normalize_label(reference[url]) != normalize_label(name):
                raise ValueError(f'第 {index} 行同一个网址对应多个台号')
            reference[url] = name
    if not reference:
        raise ValueError('对照清单为空')
    return reference

"""Local-only batch barcode decoding; one result per physical symbol."""
from dataclasses import dataclass, asdict
from pathlib import Path
from threading import Event
import csv
import json

from PIL import Image, ImageOps, ImageSequence
import pypdfium2 as pdfium
import zxingcpp

SUPPORTED = {'.png', '.jpg', '.jpeg', '.bmp', '.webp', '.tif', '.tiff', '.gif', '.pdf'}


@dataclass
class Result:
    source: str
    page: int
    status: str
    format: str = ''
    text: str = ''
    position: str = ''
    printed_table: str = ''
    actual_table: str = ''
    table_id: str = ''
    table_check: str = ''
    table_evidence: str = ''
    live_status: str = ''
    live_evidence: str = ''


def decode(image, source, page, audit=False):
    rgb = ImageOps.exif_transpose(image).convert('RGB')
    codes = zxingcpp.read_barcodes(rgb, try_rotate=True, try_downscale=True, try_invert=True)
    rows = []
    labels = []
    ocr_error = ''
    if audit:
        from table_audit import printed_labels
        try:
            labels = printed_labels(rgb)
        except Exception as exc:
            ocr_error = f'印刷台号识别失败：{exc}'
    for code in codes:
        row = Result(str(source), page, '已识别', str(code.format), code.text, str(code.position))
        if audit:
            from table_audit import label_for, apply_reference
            corners = [code.position.top_left, code.position.top_right, code.position.bottom_right, code.position.bottom_left]
            bounds = (min(p.x for p in corners), min(p.y for p in corners), max(p.x for p in corners), max(p.y for p in corners))
            row.printed_table = label_for(bounds, labels)
            apply_reference(row, {})
            if ocr_error:
                row.table_check = ocr_error
        rows.append(row)
    if audit:
        paired = {r.printed_table for r in rows if r.printed_table}
        for label in labels:
            if label[4] not in paired:
                rows.append(Result(str(source), page, '未发现码', printed_table=label[4], table_check='无法核对：未发现对应码'))
    return rows or [Result(str(source), page, '未发现码')]


def scan_file(path, cancel=None, scale=3, audit=False):
    """Yield page results; isolate bad files without interrupting a batch."""
    cancel = cancel or Event()
    path = Path(path)
    page_num = 0
    try:
        if path.suffix.lower() == '.pdf':
            with pdfium.PdfDocument(str(path)) as doc:
                for index in range(len(doc)):
                    if cancel.is_set():
                        return
                    page_num = index + 1
                    page = doc[index]
                    try:
                        # Bound the raster to avoid excessive memory on large sheets.
                        factor = min(scale, 6000 / max(page.get_size()))
                        bitmap = page.render(scale=factor)
                        try:
                            with bitmap.to_pil() as image:
                                yield decode(image, path, page_num, audit)
                        finally:
                            bitmap.close()
                    finally:
                        page.close()
        else:
            with Image.open(path) as image:
                for page_num, frame in enumerate(ImageSequence.Iterator(image), 1):
                    if cancel.is_set():
                        return
                    yield decode(frame, path, page_num, audit)
    except Exception as exc:
        yield [Result(str(path), page_num, '失败', text=str(exc))]


def export_results(path, results):
    rows = [asdict(row) for row in results]
    if Path(path).suffix.lower() == '.json':
        Path(path).write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding='utf-8')
    else:
        with open(path, 'w', encoding='utf-8-sig', newline='') as stream:
            writer = csv.DictWriter(stream, fieldnames=list(Result.__dataclass_fields__))
            writer.writeheader()
            for row in rows:
                # Prevent spreadsheet formula execution when opening untrusted codes.
                writer.writerow({key: "'" + str(value) if str(value).startswith(('=', '+', '-', '@', '\t', '\r', '\n')) else value for key, value in row.items()})

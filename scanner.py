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


def decode(image, source, page):
    rgb = ImageOps.exif_transpose(image).convert('RGB')
    codes = zxingcpp.read_barcodes(rgb, try_rotate=True, try_downscale=True, try_invert=True)
    return [Result(str(source), page, '已识别', str(c.format), c.text, str(c.position))
            for c in codes] or [Result(str(source), page, '未发现码')]


def scan_file(path, cancel=None, scale=3):
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
                    with doc[index] as page:
                        # Bound the raster to avoid excessive memory on large sheets.
                        factor = min(scale, 6000 / max(page.get_size()))
                        with page.render(scale=factor) as bitmap:
                            with bitmap.to_pil() as image:
                                yield decode(image, path, page_num)
        else:
            with Image.open(path) as image:
                for page_num, frame in enumerate(ImageSequence.Iterator(image), 1):
                    if cancel.is_set():
                        return
                    yield decode(frame, path, page_num)
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

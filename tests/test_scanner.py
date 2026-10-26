from threading import Event
from PIL import Image
import zxingcpp
from scanner import scan_file, export_results


def barcode(text, fmt=zxingcpp.BarcodeFormat.QRCode):
    code = zxingcpp.create_barcode(text, fmt)
    return Image.fromarray(zxingcpp.write_barcode_to_image(code, scale=4, add_quiet_zones=True))


def test_multiple_symbols_and_blank(tmp_path):
    canvas = Image.new('RGB', (1000, 500), 'white')
    canvas.paste(barcode('hello'), (30, 30))
    canvas.paste(barcode('1234567890', zxingcpp.BarcodeFormat.Code128), (500, 250))
    path = tmp_path / 'codes.png'
    canvas.save(path)
    rows = list(scan_file(path))[0]
    assert {r.text for r in rows} == {'hello', '1234567890'}
    blank = tmp_path / 'blank.png'
    Image.new('RGB', (200, 200), 'white').save(blank)
    assert list(scan_file(blank))[0][0].status == '未发现码'


def test_multipage_and_errors(tmp_path):
    path = tmp_path / 'pages.tiff'
    barcode('page1').save(path, save_all=True, append_images=[barcode('page2')])
    pages = list(scan_file(path))
    assert [(p[0].page, p[0].text) for p in pages] == [(1, 'page1'), (2, 'page2')]
    assert list(scan_file(tmp_path / 'missing.pdf'))[0][0].status == '失败'
    cancel = Event()
    cancel.set()
    assert list(scan_file(path, cancel)) == []


def test_exports(tmp_path):
    from scanner import Result
    rows = [Result('中文.png', 1, '已识别', 'QRCode', '=1+1')]
    path = tmp_path / 'results.csv'
    export_results(path, rows)
    assert "'=1+1" in path.read_text(encoding='utf-8-sig')
    path = tmp_path / 'results.json'
    export_results(path, rows)
    assert '中文.png' in path.read_text(encoding='utf-8')


def test_real_multipage_pdf(tmp_path):
    path = tmp_path / 'document.pdf'
    first = Image.new('RGB', (800, 600), 'white')
    first.paste(barcode('pdf-page-one'), (100, 100))
    second = Image.new('RGB', (800, 600), 'white')
    second.paste(barcode('PDF-CODE128', zxingcpp.BarcodeFormat.Code128), (100, 100))
    first.save(path, 'PDF', save_all=True, append_images=[second], resolution=150)
    pages = list(scan_file(path))
    assert [(p[0].page, p[0].text) for p in pages] == [(1, 'pdf-page-one'), (2, 'PDF-CODE128')]

from threading import Event
import time
import pytest
from scanner import Result
from wechat_reader import parse_table, qr_image, ReaderError, LiveResult
from table_audit import apply_reference


def test_circle_plus_located_without_fixed_click_coordinates():
    from PIL import Image, ImageDraw
    from wechat_reader import find_new_note_button
    image = Image.new('RGB', (1150, 740), '#f5f5f5')
    draw = ImageDraw.Draw(image)
    draw.ellipse((415, 47, 431, 63), outline='#555555', width=1)
    draw.line((420, 55, 426, 55), fill='#555555', width=1)
    draw.line((423, 52, 423, 58), fill='#555555', width=1)
    draw.ellipse((77, 52, 83, 58), outline='#aaaaaa', width=1)
    x, y = find_new_note_button(image)
    assert abs(x - 423) < 3 and abs(y - 55) < 3
    with pytest.raises(ReaderError):
        find_new_note_button(Image.new('RGB', (1150, 740), 'white'))


def test_prepare_automatically_creates_note_when_missing():
    from wechat_reader import WeChatReader
    reader = WeChatReader.__new__(WeChatReader)
    state = {'created': False}
    reader.note_editors = lambda: [(42, 'new-editor')] if state['created'] else []
    reader.editor_empty = lambda _: True
    reader.create_note = lambda: state.update(created=True)
    reader.wait_for = lambda finder, _: finder()
    reader.focused = lambda _: True
    reader.activate = lambda _: None
    reader.prepare()
    assert state['created'] and reader.note == 42 and reader.editor == 'new-editor'


def test_populated_note_is_preserved_when_creating_fresh_note():
    from wechat_reader import WeChatReader
    reader = WeChatReader.__new__(WeChatReader)
    state = {'created': False}
    reader.note_editors = lambda: [(42, 'old')] + ([(43, 'fresh')] if state['created'] else [])
    reader.editor_empty = lambda editor: editor == 'fresh'
    reader.create_note = lambda: state.update(created=True)
    reader.wait_for = lambda finder, _: finder()
    reader.focused = lambda h: h == 43
    reader.activate = lambda _: None
    reader.prepare()
    assert reader.note == 43 and reader.editor == 'fresh'


@pytest.mark.parametrize('texts,expected', [
    (['欢迎来到', 'metom（陈村店）', '桌号：C6', '1', '2', '开始点餐'], 'C6'),
    (['台号:', 'A01', '菜单'], 'A01'),
    (['桌台号：大厅8'], '大厅8'),
    (['桌号：A01', '桌号：A01'], 'A01'),
])
def test_actual_page_table(texts, expected):
    assert parse_table(texts) == expected


@pytest.mark.parametrize('texts', [
    ['C6', '1', '2', '开始点餐'], ['桌号：A01', '桌号：A02'],
    ['账号：13800000000', '商品编号：123'], ['桌号：'],
])
def test_no_guessing_or_ambiguous_page(texts):
    with pytest.raises(ReaderError):
        parse_table(texts)


def test_qr_payload_preserved():
    import zxingcpp
    payload = 'https://example.com/qrcode/123?dId=9007199254740999&x=%E6%A1%8C'
    assert [r.text for r in zxingcpp.read_barcodes(qr_image(payload))] == [payload]


def test_reference_does_not_override_actual_wechat_page():
    row = Result('a.png', 1, '已识别', text='https://example.com', printed_table='A01',
                 actual_table='A09', live_status='已读取', table_evidence='微信实际页面')
    apply_reference(row, {row.text: 'A01'})
    assert row.actual_table == 'A09' and row.table_check == '不一致'
    row.live_status = '读取失败'
    apply_reference(row, {row.text: 'A01'})
    assert row.actual_table == ''


def test_live_batch_updates_only_matching_rows(monkeypatch, desktop_app):
    app = desktop_app
    app.auto_open.set(False)
    payload = 'https://example.com/code'
    app.results = [Result('sheet.png', 1, '已识别', text=payload, printed_table='C06'),
                   Result('sheet.png', 2, '已识别', text=payload, printed_table='C6')]
    calls = []
    class FakeReader:
        def __init__(self, *_):
            pass
        def prepare(self):
            pass
        def read(self, text, sequence):
            calls.append((text, sequence))
            return LiveResult('C6', '美团点餐', 'evidence.png')
    monkeypatch.setattr('wechat_reader.WeChatReader', FakeReader)
    app.start_live()
    deadline = time.monotonic() + 10
    while app.running and time.monotonic() < deadline:
        app.update()
        time.sleep(.02)
    assert not app.running
    assert calls == [(payload, 1)]
    assert [r.actual_table for r in app.results] == ['C6', 'C6']
    assert all(r.live_status == '已读取' and r.live_evidence == 'evidence.png' for r in app.results)
    assert app.results[0].table_check == '不一致'  # No silent zero-padding assumptions.
    assert app.results[1].table_check == '一致'


def test_live_failure_stops_queue_without_stale_table(monkeypatch, desktop_app):
    app = desktop_app
    monkeypatch.setattr('app.messagebox.showerror', lambda *_: None)
    app.results = [Result('a.png', 1, '已识别', text='https://example.com/1', actual_table='old'),
                   Result('a.png', 1, '已识别', text='https://example.com/2', actual_table='old')]
    calls = []
    class BrokenReader:
        def __init__(self, *_):
            pass
        def prepare(self):
            pass
        def read(self, text, sequence):
            calls.append(text)
            raise ReaderError('无法确认新页面')
    monkeypatch.setattr('wechat_reader.WeChatReader', BrokenReader)
    app.start_live()
    deadline = time.monotonic() + 10
    while app.running and time.monotonic() < deadline:
        app.update()
        time.sleep(.02)
    assert not app.running and len(calls) == 1
    assert all(not r.actual_table for r in app.results)
    assert app.results[0].live_status.startswith('读取失败')
    assert app.results[1].live_status.startswith('未执行')


def test_preparation_error_is_shown_and_attached_to_first_row(monkeypatch, desktop_app):
    app = desktop_app
    errors = []
    monkeypatch.setattr('app.messagebox.showerror', lambda title, text: errors.append((title, text)))
    app.results = [Result('a.png', 1, '已识别', text='https://example.com/1'),
                   Result('a.png', 1, '已识别', text='https://example.com/2')]
    class UnavailableReader:
        def __init__(self, *_):
            pass
        def prepare(self):
            raise ReaderError('未找到已登录微信')
    monkeypatch.setattr('wechat_reader.WeChatReader', UnavailableReader)
    app.start_live()
    deadline = time.monotonic() + 10
    while app.running and time.monotonic() < deadline:
        app.update()
        time.sleep(.02)
    assert not app.running
    assert errors == [('微信读取未完成', '未找到已登录微信')]
    assert app.results[0].live_status == '读取失败：未找到已登录微信'
    assert app.results[1].live_status.startswith('未执行')

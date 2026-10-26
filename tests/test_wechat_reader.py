from threading import Event
import time
import pytest
from scanner import Result
from wechat_reader import parse_table, qr_image, ReaderError, LiveResult
from table_audit import apply_reference


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

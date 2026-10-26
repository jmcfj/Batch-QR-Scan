import time
from scanner import Result
from wechat_reader import LiveResult
from test_scanner import barcode
from PIL import Image
from reading_profiles import TextRegion


def test_one_scan_button_waits_for_manual_preparation_then_reads(monkeypatch, desktop_app, tmp_path):
    app = desktop_app
    path = tmp_path / '桌牌.png'
    barcode('https://example.com/table/1').save(path)
    app.add([path])
    preparation, calls = {}, []
    class FakePreparation:
        def __init__(self, parent, count, ready, cancel):
            preparation.update(count=count, ready=ready, cancel=cancel)
    class FakeReader:
        def __init__(self, *_):
            pass
        def prepare(self):
            assert self.manual_note is True
            assert callable(self.selector)
            calls.append('prepared')
        def read(self, text, sequence):
            calls.append(text)
            return LiveResult('A1', '系统')
    monkeypatch.setattr('workflow_ui.PreparationDialog', FakePreparation)
    monkeypatch.setattr('wechat_reader.WeChatReader', FakeReader)
    app.start_button.invoke()
    deadline = time.monotonic() + 10
    while not preparation and time.monotonic() < deadline:
        app.update()
        time.sleep(.02)
    assert preparation['count'] == 1 and not app.running
    assert not calls  # Switching windows to manually open a note is safe here.
    assert not hasattr(app, 'live_button')
    preparation['ready']()
    while app.running and time.monotonic() < deadline:
        app.update()
        time.sleep(.02)
    assert not app.running and calls == ['prepared', 'https://example.com/table/1']
    assert app.results[0].actual_table == 'A1'


def test_cancel_preparation_preserves_scan_results(monkeypatch, desktop_app):
    app = desktop_app
    app.results = [Result('sheet.png', 1, '已识别', text='https://example.com/1')]
    class CancelPreparation:
        def __init__(self, parent, count, ready, cancel):
            cancel()
    monkeypatch.setattr('workflow_ui.PreparationDialog', CancelPreparation)
    app.show_preparation(1)
    assert app.results[0].text == 'https://example.com/1' and not app.running


def test_region_picker_confirms_exact_selected_region(desktop_app):
    from types import SimpleNamespace
    from workflow_ui import RegionPicker
    app = desktop_app
    results = []
    ticket = {'key': 'test-system', 'label': '测试点餐系统',
              'image': Image.new('RGB', (400, 600), 'white'),
              'regions': [TextRegion('桌号：A01', (.65, .38, .9, .42))]}
    dialog = RegionPicker(app, ticket, results.append)
    dialog.begin(SimpleNamespace(x=.6 * dialog.dw, y=.35 * dialog.dh))
    dialog.drag(SimpleNamespace(x=.95 * dialog.dw, y=.5 * dialog.dh))
    dialog.finish_selection(SimpleNamespace(x=.95 * dialog.dw, y=.5 * dialog.dh))
    assert str(dialog.confirm['state']) == 'normal'
    assert 'A01' in dialog.feedback.get()
    dialog.confirm.invoke()
    assert len(results) == 1 and results[0].anchor == '桌号'
    assert results[0].rect == (.6, .35, .95, .5)

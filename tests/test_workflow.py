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
    calls = []
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
    monkeypatch.setattr('wechat_reader.WeChatReader', FakeReader)
    app.start_button.invoke()
    deadline = time.monotonic() + 10
    while str(app.preparation_panel.ready_button['state']) != 'normal' and time.monotonic() < deadline:
        app.update()
        time.sleep(.02)
    assert '1 个' in app.preparation_panel.heading.get() and not app.running
    assert app.content_tabs.select() == str(app.guide_tab)
    assert not any(isinstance(w, __import__('tkinter').Toplevel) for w in app.winfo_children())
    assert not calls  # Switching windows to manually open a note is safe here.
    assert not hasattr(app, 'live_button')
    app.preparation_panel.ready_button.invoke()
    while app.running and time.monotonic() < deadline:
        app.update()
        time.sleep(.02)
    assert not app.running and calls == ['prepared', 'https://example.com/table/1']
    assert app.results[0].actual_table == 'A1'


def test_cancel_preparation_preserves_scan_results(monkeypatch, desktop_app):
    app = desktop_app
    app.results = [Result('sheet.png', 1, '已识别', text='https://example.com/1')]
    app.show_preparation(1)
    app.preparation_panel.cancel_button.invoke()
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


def test_main_guide_has_images_and_removed_controls(desktop_app):
    import tkinter as tk
    from tkinter import ttk
    app = desktop_app
    def descendants(widget):
        for child in widget.winfo_children():
            yield child
            yield from descendants(child)
    labels = [str(w.cget('text')) for w in descendants(app)
              if isinstance(w, (ttk.Button, ttk.Checkbutton, ttk.Label, tk.Label))]
    assert '添加文件夹' not in labels
    assert '识别码上方的印刷台号' not in labels
    assert not any('对照设置' in text or '台号位置模板' in text for text in labels)
    assert len(app.preparation_panel.photos) == 2
    assert any('不要动鼠标' in text and '框选' in text for text in labels)
    assert not isinstance(app.preparation_panel, tk.Toplevel)

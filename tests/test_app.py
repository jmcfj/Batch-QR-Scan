import time
from app import App
from scanner import Result
from test_scanner import barcode


def test_desktop_workflow(tmp_path, desktop_app):
    path = tmp_path / '中文.png'
    barcode('desktop-test').save(path)
    app = desktop_app
    try:
        app.withdraw()
        app.add([path, path])
        assert len(app.files) == 1
        app.start()
        deadline = time.monotonic() + 10
        while app.running and time.monotonic() < deadline:
            app.update()
            time.sleep(.02)
        assert not app.running
        assert app.results[0].text == 'desktop-test'
        app.results.append(Result('blank.png', 1, '未发现码'))
        app.only_codes.set(True)
        app.refresh()
        assert len(app.table.get_children()) == 1
        app.query.set('absent')
        assert not app.table.get_children()
        app.query.set('desktop')
        app.table.selection_set('0')
        app.copy()
        assert app.clipboard_get() == 'desktop-test'
        app.clear()
        assert not app.files and not app.results
    finally:
        app.clear()

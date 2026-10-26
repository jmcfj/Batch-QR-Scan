import pytest
from links import web_url


@pytest.mark.parametrize('value, expected', [
    (' https://example.com/path?q=中文#top ', 'https://example.com/path?q=中文#top'),
    ('http://example.com:8080/a', 'http://example.com:8080/a'),
    ('www.example.com', 'https://www.example.com'),
    ('HTTPS://example.com', 'HTTPS://example.com'),
    ('javascript:alert(1)', None), ('file:///C:/test', None),
    ('weixin://test', None), ('https://', None), ('plain text', None),
    ('https://example.com\nevil', None), ('https://a:bad/', None),
    ('https://user:pass@example.com', None),
])
def test_web_url(value, expected):
    assert web_url(value) == expected


def test_web_actions(monkeypatch, tmp_path, desktop_app):
    import time
    from app import App
    from scanner import Result
    from test_scanner import barcode
    opened = []
    monkeypatch.setattr('app.webbrowser.open', lambda url, new: opened.append(url) or True)
    app = desktop_app
    try:
        app.withdraw()
        path = tmp_path / 'url.png'
        barcode('https://example.com/result').save(path)
        app.add([path])
        app.start()
        deadline = time.monotonic() + 10
        while app.running and time.monotonic() < deadline:
            app.update()
            time.sleep(.02)
        assert opened == ['https://example.com/result']
        app.table.selection_set('0')
        app.details()
        assert str(app.open_button['state']) == 'normal'
        app.open_webpage()
        assert len(opened) == 2
        app.results.append(Result('bad.png', 1, '已识别', text='javascript:alert(1)'))
        app.refresh()
        app.table.selection_set('1')
        app.details()
        app.open_webpage()
        assert str(app.open_button['state']) == 'disabled'
        assert len(opened) == 2
    finally:
        app.clear()

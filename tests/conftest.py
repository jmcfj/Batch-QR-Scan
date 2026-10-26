import pytest
from app import App


@pytest.fixture(scope='session')
def desktop(tmp_path_factory):
    app = App(settings_path=tmp_path_factory.mktemp('settings') / 'reference.json')
    app.withdraw()
    yield app
    app.destroy()


@pytest.fixture
def desktop_app(desktop):
    desktop.clear()
    desktop.query.set('')
    desktop.only_codes.set(False)
    desktop.auto_open.set(True)
    desktop.audit_mode.set(False)
    desktop.reference = {}
    desktop.reference_evidence = '独立对照清单'
    yield desktop

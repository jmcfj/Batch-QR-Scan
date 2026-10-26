import pytest
from app import App


@pytest.fixture(scope='session')
def desktop():
    app = App()
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
    yield desktop

from pathlib import Path
import pytest
from PIL import Image
from reading_profiles import (ReadingProfile, ProfileStore, TextRegion, RegionReadError,
                              system_identity, read_regions, interpret_texts, validate_rect)


def test_selected_region_reads_value_and_ignores_other_page_numbers():
    profile = ReadingProfile('system', '点餐', (.6, .35, .95, .5), .5, 'alnum', '桌号')
    regions = [TextRegion('价格：28', (.05, .35, .3, .45)),
               TextRegion('桌号：A01', (.65, .38, .9, .42)),
               TextRegion('桌号：B99', (.1, .65, .3, .7))]
    assert read_regions(profile, regions, (400, 800)) == 'A01'
    regions[1].text = '桌号：a2'
    assert read_regions(profile, regions, (800, 1600)) == 'a2'
    with pytest.raises(RegionReadError):
        read_regions(profile, regions, (1200, 800))


def test_label_or_plain_value_and_ambiguity():
    assert interpret_texts(['桌号：', 'C06']) == ('C06', '桌号')
    assert interpret_texts(['a01']) == ('a01', '')
    assert interpret_texts(['A01', 'a1']) == ('A01', '')
    with pytest.raises(RegionReadError):
        interpret_texts(['A01', '28'])
    with pytest.raises(RegionReadError):
        interpret_texts(['￥28.00'])
    with pytest.raises(RegionReadError):
        validate_rect((0, 0, 1, 1))


def test_templates_are_scoped_to_system_and_persisted(tmp_path):
    first, _ = system_identity('美团点餐', 'https://rms.meituan.com/table/one', ['https://servicewechat.com/wx1fde2c33280d64b6/596/page-frame.html'])
    again, _ = system_identity('美团点餐', 'https://rms.meituan.com/table/two', ['https://servicewechat.com/wx1fde2c33280d64b6/600/page-frame.html'])
    other, _ = system_identity('收钱吧', 'https://wx-kaci.shouqianba.com/qrcode/shop', ['https://servicewechat.com/wx1234567890123456/1/page-frame.html'])
    assert first == again and first != other
    path = tmp_path / 'profiles.json'
    store = ProfileStore(path)
    store.save(ReadingProfile(first, '美团点餐', (.6, .35, .95, .5), .5, 'alnum', '桌号'))
    restored = ProfileStore(path)
    assert restored.get(first).anchor == '桌号'
    assert restored.get(other) is None
    restored.forget(first)
    assert ProfileStore(path).get(first) is None


def test_manual_preparation_never_clicks_create_note():
    from wechat_reader import WeChatReader, ReaderError
    reader = WeChatReader.__new__(WeChatReader)
    reader.manual_note = True
    reader.note_editors = lambda: []
    reader.create_note = lambda: pytest.fail('User requested manual note creation')
    with pytest.raises(ReaderError, match='手动'):
        reader.prepare()


def test_existing_profile_is_reused_without_prompt(monkeypatch, tmp_path):
    import win32gui
    from wechat_reader import WeChatReader
    store = ProfileStore(tmp_path / 'profiles.json')
    payload = 'https://example.com/table/1'
    key, label = system_identity('系统甲', payload)
    store.save(ReadingProfile(key, label, (.6, .35, .95, .5), .5, 'alnum', '桌号'))
    reader = WeChatReader.__new__(WeChatReader)
    reader.profile_store = store
    reader.selector = lambda _: pytest.fail('Saved profile must not ask again')
    reader.page_layout = lambda _: ([TextRegion('桌号：A2', (.65, .38, .9, .42))], [], (400, 800), ['桌号：A2'])
    monkeypatch.setattr(win32gui, 'GetWindowText', lambda _: '系统甲')
    value, _, _, calibrated = reader.guided_table(1, payload, 5)
    assert value == 'A2' and not calibrated


def test_new_system_asks_once_and_then_reuses(monkeypatch, tmp_path):
    import win32gui
    from wechat_reader import WeChatReader
    reader = WeChatReader.__new__(WeChatReader)
    reader.profile_store = ProfileStore(tmp_path / 'profiles.json')
    reader.page_layout = lambda _: ([TextRegion('桌号：A1', (.65, .38, .9, .42))], [], (400, 800), ['桌号：A1'])
    reader.focused = lambda _: True
    reader.screenshot = lambda _: (Image.new('RGB', (400, 800), 'white'), (0, 0, 400, 800))
    reader.activate = lambda _: None
    calls = []
    def select(ticket):
        calls.append(ticket['key'])
        return ReadingProfile(ticket['key'], ticket['label'], (.6, .35, .95, .5), .5, 'alnum', '桌号')
    reader.selector = select
    monkeypatch.setattr(win32gui, 'GetWindowText', lambda _: '系统乙')
    assert reader.guided_table(1, 'https://b.example/1', 5)[0] == 'A1'
    assert reader.guided_table(1, 'https://b.example/2', 5)[0] == 'A1'
    assert len(calls) == 1

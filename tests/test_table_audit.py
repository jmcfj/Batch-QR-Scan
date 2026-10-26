import pytest
from scanner import Result
from table_audit import label_for, apply_reference, load_reference


@pytest.mark.parametrize('printed,actual,expected', [
    ('A01', 'A1', '一致'), ('A02', 'a2', '一致'), ('a01', 'A001', '一致'),
    ('C06', 'c6', '一致'), ('A00', 'a0', '一致'), ('Ａ０１', 'a1', '一致'),
    ('A01', 'A2', '不一致'), ('A01', 'B01', '不一致'),
    ('A-01', 'A01', '不一致'), ('A01', 'A10', '不一致'),
])
def test_comparison_ignores_padding_and_case_without_changing_original(printed, actual, expected):
    from table_audit import compare_table
    row = Result('x.png', 1, '已识别', printed_table=printed, actual_table=actual)
    compare_table(row)
    assert row.table_check == expected
    assert row.printed_table == printed and row.actual_table == actual


def test_wifi_text_not_mistaken_for_orphan_table():
    from table_audit import heading_label
    assert heading_label('A01扫码点餐') == 'A01'
    assert heading_label('WIF1密码:mt123456') == ''
    assert heading_label('W1F1 密码:mt123456') == ''


def test_match_geometry_and_ambiguity():
    labels = [(50, 35, 140, 55, 'A01'), (195, 35, 285, 55, 'A02')]
    assert label_for((61, 64, 133, 136), labels) == 'A01'
    assert label_for((207, 64, 279, 136), labels) == 'A02'
    assert label_for((61, 241, 133, 313), labels) == ''
    assert label_for((61, 64, 133, 136), labels + [(60, 40, 100, 50, 'B01')]) == ''


def test_internal_id_never_infers_table():
    row = Result('sheet.png', 1, '已识别', text='https://example.com/qrcode/shop?dId=123456', printed_table='A01')
    apply_reference(row, {})
    assert row.table_id == '123456'
    assert row.actual_table == ''
    assert row.table_check == '待核实：缺少实际台号'
    apply_reference(row, {row.text: 'A02'})
    assert row.table_check == '不一致'
    assert row.table_evidence == '独立对照清单'
    apply_reference(row, {row.text: 'A01'})
    assert row.table_check == '一致'
    apply_reference(row, {})
    assert row.actual_table == ''  # Clear stale values when replacing reference.


def test_explicit_name_and_missing_label():
    row = Result('sheet.png', 1, '已识别', text='https://example.com/?tableName=A01&tableId=987', printed_table='A01')
    apply_reference(row, {})
    assert row.actual_table == 'A01' and row.table_check == '一致'
    row.printed_table = ''
    apply_reference(row, {})
    assert row.table_check == '待核实：未读到印刷台号'


def test_reference_csv(tmp_path):
    path = tmp_path / 'reference.csv'
    path.write_text('url,actual_table\nhttps://example.com/one,A01\n', encoding='utf-8-sig')
    assert load_reference(path) == {'https://example.com/one': 'A01'}
    path.write_text('url,actual_table\nhttps://example.com/one,A01\nhttps://example.com/one,A02\n', encoding='utf-8')
    with pytest.raises(ValueError, match='多个台号'):
        load_reference(path)
    path.write_text('printed_table,text\nA01,https://example.com/one\n', encoding='utf-8')
    with pytest.raises(ValueError, match='两列'):
        load_reference(path)


def test_swapped_codes_compare_independently(monkeypatch):
    from PIL import Image
    from scanner import decode
    from test_scanner import barcode
    image = Image.new('RGB', (1000, 500), 'white')
    image.paste(barcode('https://example.com/?tableName=A02'), (30, 100))
    image.paste(barcode('https://example.com/?tableName=A01'), (530, 100))
    monkeypatch.setattr('table_audit.printed_labels', lambda _: [
        (35, 65, 135, 90, 'A01'), (535, 65, 635, 90, 'A02')])
    rows = decode(image, 'swapped.png', 1, audit=True)
    assert len(rows) == 2
    assert {(r.printed_table, r.actual_table, r.table_check) for r in rows} == {
        ('A01', 'A02', '不一致'), ('A02', 'A01', '不一致')}


def test_label_without_code_is_not_silently_ignored(monkeypatch):
    from PIL import Image
    from scanner import decode
    monkeypatch.setattr('table_audit.printed_labels', lambda _: [(35, 65, 135, 90, 'A01')])
    rows = decode(Image.new('RGB', (200, 200), 'white'), 'blank.png', 1, audit=True)
    assert len(rows) == 1
    assert rows[0].printed_table == 'A01' and rows[0].status == '未发现码'


def test_backend_originals_resolve_actual_tables_and_conflicts(tmp_path):
    from test_scanner import barcode
    from table_audit import load_reference_folder
    first = 'https://example.com/qrcode/shop?dId=123456'
    second = 'https://example.com/qrcode/shop?dId=999999'
    barcode(first).save(tmp_path / 'A01.png')
    barcode(second).save(tmp_path / 'A02.png')
    (tmp_path / 'design.cdr').write_bytes(b'ignored')
    reference = load_reference_folder(tmp_path)
    assert reference == {first: 'A01', second: 'A02'}
    row = Result('sheet.png', 1, '已识别', text=second, printed_table='A01')
    apply_reference(row, reference, '后台原始码文件名')
    assert row.actual_table == 'A02' and row.table_check == '不一致'
    assert row.table_evidence == '后台原始码文件名'
    barcode(first).save(tmp_path / 'C01.png')
    with pytest.raises(ValueError, match='原码冲突'):
        load_reference_folder(tmp_path)


def test_bad_backend_original_not_accepted(tmp_path):
    from PIL import Image
    from table_audit import load_reference_folder
    Image.new('RGB', (150, 150), 'white').save(tmp_path / 'A01.png')
    with pytest.raises(ValueError, match='可识别'):
        load_reference_folder(tmp_path)


def test_reference_remembered_without_user_data_in_repo(tmp_path):
    from table_audit import save_reference_state, read_reference_state
    path = tmp_path / 'settings' / 'reference.json'
    reference = {'https://example.com/?dId=123': 'A01'}
    save_reference_state(path, reference, '后台原始码文件名：原码')
    assert read_reference_state(path) == (reference, '后台原始码文件名：原码')
    path.write_text('corrupt', encoding='utf-8')
    assert read_reference_state(path)[0] == {}


def test_import_original_folder_updates_existing_results(monkeypatch, tmp_path, desktop_app):
    from test_scanner import barcode
    from table_audit import read_reference_state
    app = desktop_app
    url = 'https://example.com/shop?dId=12345'
    barcode(url).save(tmp_path / 'A08.png')
    app.results = [Result('sheet.png', 1, '已识别', text=url, printed_table='A09')]
    monkeypatch.setattr('app.filedialog.askdirectory', lambda **_: str(tmp_path))
    app.import_original_folder()
    assert app.results[0].actual_table == 'A08'
    assert app.results[0].table_check == '不一致'
    assert read_reference_state(app.settings_path)[0] == {url: 'A08'}

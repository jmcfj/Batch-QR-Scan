import pytest
from scanner import Result
from table_audit import label_for, apply_reference, load_reference


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

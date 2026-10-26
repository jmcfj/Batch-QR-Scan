from PIL import Image
from file_preview import load_preview


def test_image_and_pdf_preview(tmp_path):
    path = tmp_path / 'image.png'
    Image.new('RGB', (400, 300), 'white').save(path)
    image, text = load_preview(path)
    assert image.size == (400, 300) and '400' in text
    path = tmp_path / 'two-pages.pdf'
    image.save(path, save_all=True, append_images=[image])
    preview, text = load_preview(path)
    assert preview.width > 0 and '2 页' in text


def test_import_visible_and_switchable(desktop_app, tmp_path):
    app = desktop_app
    first, second = tmp_path / '餐厅桌牌.png', tmp_path / '第二张.png'
    Image.new('RGB', (320, 240), 'white').save(first)
    Image.new('RGB', (640, 480), 'gray').save(second)
    app.add([first, second])
    assert app.file_list.get(0, 'end') == (first.name, second.name)
    assert app.preview_image.size == (640, 480)
    assert str(second) == app.file_path.get()
    app.file_list.selection_clear(0, 'end')
    app.file_list.selection_set(0)
    app.show_file_preview()
    assert app.preview_image.size == (320, 240)
    assert str(first) in app.preview_info.get()
    app.clear()
    assert app.preview_image is None and not app.files

"""Read a local image or the first PDF page for the import preview."""
from pathlib import Path
from PIL import Image, ImageOps


def load_preview(path):
    path = Path(path)
    if path.suffix.lower() == '.pdf':
        import pypdfium2 as pdfium
        with pdfium.PdfDocument(str(path)) as doc:
            count = len(doc)
            page = doc[0]
            try:
                bitmap = page.render(scale=min(1.5, 1600 / max(page.get_size())))
                try:
                    image = bitmap.to_pil().convert('RGB').copy()
                finally:
                    bitmap.close()
            finally:
                page.close()
        return image, f'PDF · 共 {count} 页 · 正在预览第 1 页'
    with Image.open(path) as source:
        size = source.size
        image = ImageOps.exif_transpose(source).convert('RGB')
        image.thumbnail((1800, 1800))
        return image.copy(), f'图片 · {size[0]} × {size[1]} 像素'

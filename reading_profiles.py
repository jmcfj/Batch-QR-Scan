"""User-selected table regions, partitioned by ordering-system identity."""
from dataclasses import dataclass, asdict
from pathlib import Path
from urllib.parse import urlsplit
import hashlib
import json
import math
import re
from table_audit import comparison_key, normalize_label


class RegionReadError(ValueError):
    pass


@dataclass
class TextRegion:
    text: str
    rect: tuple


@dataclass
class ReadingProfile:
    key: str
    label: str
    rect: tuple
    aspect: float
    kind: str
    anchor: str = ''


def validate_rect(rect):
    if len(rect) != 4 or not all(isinstance(v, (int, float)) and math.isfinite(v) for v in rect):
        raise RegionReadError('台号区域坐标无效')
    x0, y0, x1, y1 = rect
    if not (0 <= x0 < x1 <= 1 and 0 <= y0 < y1 <= 1):
        raise RegionReadError('请在截图内框选一个非空区域')
    if (x1 - x0) * (y1 - y0) > .35:
        raise RegionReadError('选区太大，请只框出台号及旁边的标签')
    return tuple(float(v) for v in rect)


def system_identity(title, payload, documents=()):
    appids = sorted(set(re.findall(r'wx[0-9a-z]{16}', ' '.join(documents), flags=re.I)))
    host = (urlsplit(payload).hostname or '').lower()
    label = f'{title} · {host}'
    raw = json.dumps([title, host, appids], ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(raw.encode('utf-8')).hexdigest()[:24], label


def selected_texts(regions, rect):
    x0, y0, x1, y1 = validate_rect(rect)
    selected = []
    for node in regions:
        a, b, c, d = node.rect
        area = max(0, c - a) * max(0, d - b)
        overlap = max(0, min(x1, c) - max(x0, a)) * max(0, min(y1, d) - max(y0, b))
        center_inside = x0 <= (a + c) / 2 <= x1 and y0 <= (b + d) / 2 <= y1
        if area and (center_inside or overlap / area >= .35):
            selected.append(node)
    selected.sort(key=lambda n: (round(n.rect[1] / .02), n.rect[0]))
    return [n.text for n in selected]


ANCHORS = r'(桌台编号|桌台号|餐桌号|桌号|台号|桌台)'


def value_kind(value):
    normalized = normalize_label(value)
    if re.fullmatch(r'[A-Z]{1,8}[-_]?\d{1,8}', normalized):
        return 'alnum'
    if re.fullmatch(r'\d{1,8}', normalized):
        return 'number'
    if re.fullmatch(r'[\u4e00-\u9fffA-Z]{1,16}[-_]?\d{1,8}', normalized):
        return 'mixed'
    return 'named'


def interpret_texts(texts):
    lines = [t.strip() for text in texts for t in str(text).splitlines() if t.strip()]
    labelled, plain, anchors = {}, {}, []
    invalid = {'未选择', '请选择', '未绑定', '未开台', '加载中', '开始点餐', '推荐', '购物车'}
    for line in lines:
        label = re.fullmatch(ANCHORS + r'\s*[:：]?\s*(\S{1,24})?', line)
        if label:
            anchors.append(label[1])
            if label[2] and label[2] not in invalid:
                labelled.setdefault(comparison_key(label[2]), label[2])
            continue
        if value_kind(line) != 'named':
            plain.setdefault(comparison_key(line), line)
    if len(labelled) == 1:
        return next(iter(labelled.values())), anchors[0]
    if len(labelled) > 1 or len(plain) != 1:
        raise RegionReadError('选区内没有唯一台号，请缩小到台号及标签，避开人数、价格等数字')
    if any(re.fullmatch(r'[A-Za-z]+', t) for t in lines) and value_kind(next(iter(plain.values()))) == 'number':
        raise RegionReadError('台号文字被拆分，需通过选区图片读取完整台号')
    return next(iter(plain.values())), anchors[0] if anchors else ''


def read_ocr(image, rect):
    import numpy as np
    from table_audit import ocr_engine
    x0, y0, x1, y1 = validate_rect(rect)
    crop = image.crop((round(x0 * image.width), round(y0 * image.height), round(x1 * image.width), round(y1 * image.height)))
    if crop.width < 3 or crop.height < 3:
        raise RegionReadError('选区太小，请重新框选')
    scale = min(3, 1200 / max(crop.size))
    crop = crop.resize((max(1, round(crop.width * scale)), max(1, round(crop.height * scale))))
    found, _ = ocr_engine()(np.asarray(crop.convert('RGB')))
    texts = [text for _, text, score in found or [] if score >= .8]
    value, anchor = interpret_texts(texts)
    return value, anchor, texts


def verify_value(profile, value, anchor):
    if profile.anchor and anchor != profile.anchor:
        raise RegionReadError('台号标签与已保存模板不一致，未采用该结果')
    if value_kind(value) != profile.kind:
        raise RegionReadError('台号格式与已保存模板不一致，未采用该结果')
    return value


def verify_geometry(profile, size):
    if size[1] <= 0 or abs((size[0] / size[1]) / profile.aspect - 1) > .15:
        raise RegionReadError('点餐窗口比例变化较大，请恢复原窗口尺寸或重新指定台号位置')


def read_regions(profile, regions, size):
    verify_geometry(profile, size)
    value, anchor = interpret_texts(selected_texts(regions, profile.rect))
    return verify_value(profile, value, anchor)


class ProfileStore:
    def __init__(self, path):
        self.path = Path(path)
        self.profiles = {}
        try:
            data = json.loads(self.path.read_text(encoding='utf-8'))
            for key, value in data.get('profiles', {}).items():
                try:
                    profile = ReadingProfile(**value)
                    validate_rect(profile.rect)
                    if profile.key == key and profile.aspect > 0 and math.isfinite(profile.aspect) and profile.kind in ('alnum', 'number', 'mixed', 'named'):
                        self.profiles[key] = profile
                except (TypeError, ValueError):
                    continue
        except (OSError, ValueError, TypeError, AttributeError):
            pass

    def get(self, key):
        return self.profiles.get(key)

    def save(self, profile):
        validate_rect(profile.rect)
        updated = dict(self.profiles)
        updated[profile.key] = profile
        self._write(updated)

    def forget(self, key):
        updated = dict(self.profiles)
        updated.pop(key, None)
        self._write(updated)

    def _write(self, updated):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix('.tmp')
        temporary.write_text(json.dumps({'version': 1, 'profiles': {k: asdict(v) for k, v in updated.items()}}, ensure_ascii=False, indent=2), encoding='utf-8')
        temporary.replace(self.path)
        self.profiles = updated

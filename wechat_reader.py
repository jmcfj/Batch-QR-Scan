"""Read table numbers through a visible, logged-in Windows WeChat session.

Uses a dedicated temporary WeChat note, not messages to contacts. Each QR is
regenerated separately and verified again inside WeChat's image viewer before
recognition. A fresh mini-program window is required for every result.
"""
from dataclasses import dataclass
from pathlib import Path
from io import BytesIO
import re
import time
import json


class ReaderError(RuntimeError):
    pass


@dataclass
class LiveResult:
    table: str
    app: str
    evidence: str = ''


def parse_table(texts):
    """Only accept explicitly labelled table numbers, never other page numbers."""
    lines = [str(t).strip() for t in texts if str(t).strip()]
    candidates = set()
    prefix = r'(?:桌台编号|桌台号|餐桌号|桌号|台号)\s*[:：]'
    token = r'[A-Za-z0-9\u4e00-\u9fff][A-Za-z0-9\u4e00-\u9fff _\-]{0,23}'
    for i, line in enumerate(lines):
        match = re.fullmatch(prefix + r'\s*(' + token + r')', line)
        if match:
            candidates.add(match[1].strip())
        elif re.fullmatch(prefix + r'\s*', line) and i + 1 < len(lines):
            if re.fullmatch(token, lines[i + 1]):
                candidates.add(lines[i + 1])
    if len(candidates) != 1:
        raise ReaderError('页面未显示唯一明确的桌号，或含多个不同桌号')
    return next(iter(candidates))


def qr_image(payload):
    import zxingcpp
    from PIL import Image
    code = zxingcpp.create_barcode(payload, zxingcpp.BarcodeFormat.QRCode)
    image = Image.fromarray(zxingcpp.write_barcode_to_image(code, scale=8, add_quiet_zones=True)).convert('RGB')
    found = zxingcpp.read_barcodes(image)
    if len(found) != 1 or found[0].text != payload:
        raise ReaderError('单码图生成校验失败')
    return image


def copy_qr(payload):
    """Place a single QR on the local clipboard. No message is sent."""
    import win32clipboard as cb
    image = qr_image(payload)
    stream = BytesIO()
    image.save(stream, 'BMP')
    cb.OpenClipboard()
    try:
        cb.EmptyClipboard()
        cb.SetClipboardData(cb.CF_DIB, stream.getvalue()[14:])
    finally:
        cb.CloseClipboard()


def check_runtime():
    """Read-only packaging check: no window activation or input."""
    import uiautomation as auto
    import win32gui
    from table_audit import ocr_engine
    root = auto.GetRootControl()
    _ = root.Name  # Exercises the generated UIAutomation COM bindings.
    qr_image('batch-qr-runtime-check')
    ocr_engine()
    return {'ui_automation': True, 'qr': True, 'ocr_models': True}


def find_new_note_button(image):
    """Locate WeChat's observed circle-plus glyph, never a fixed screen point."""
    import cv2
    import numpy as np
    gray = cv2.cvtColor(np.asarray(image.convert('RGB')), cv2.COLOR_RGB2GRAY)
    # The plus button is beside the search field in the upper-left toolbar.
    height = min(125, gray.shape[0])
    width = min(gray.shape[1], max(480, int(gray.shape[1] * .65)))
    roi = gray[:height, :width]
    background = float(np.median(roi[28:min(80, height), 60:width]))
    circles = cv2.HoughCircles(roi, cv2.HOUGH_GRADIENT, 1, 18,
                               param1=70, param2=11, minRadius=6, maxRadius=15)
    candidates = []
    for cx, cy, radius in (circles[0] if circles is not None else []):
        cx, cy, radius = round(float(cx)), round(float(cy)), round(float(radius))
        if cx < 80 or cy < 28 or cy >= height - 8:
            continue
        best = -1
        center = (cx, cy)
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                x, y = cx + dx, cy + dy
                d = max(2, radius // 3)
                if x - d < 0 or x + d >= roi.shape[1] or y - d < 0 or y + d >= roi.shape[0]:
                    continue
                cross = np.concatenate((roi[y, x-d:x+d+1], roi[y-d:y+d+1, x]))
                corners = np.array([roi[y-d, x-d], roi[y-d, x+d], roi[y+d, x-d], roi[y+d, x+d]], dtype=float)
                if abs(float(corners.mean()) - background) > 35:
                    continue  # Text glyphs in the chat title are not toolbar icons.
                score = abs(float(corners.mean()) - float(cross.mean()))
                if score > best:
                    best, center = score, (x, y)
        cx, cy = center
        rim = []
        for angle in np.linspace(0, 2 * np.pi, 32, endpoint=False):
            samples = []
            for r in (radius - 1.5, radius - 1, radius - .5, radius, radius + .5, radius + 1):
                x, y = round(cx + r * np.cos(angle)), round(cy + r * np.sin(angle))
                if 0 <= y < roi.shape[0] and 0 <= x < roi.shape[1]:
                    samples.append(abs(background - float(roi[y, x])))
            rim.append(max(samples, default=0))
        if best > 45 and sum(v > 35 for v in rim) >= 28:
            candidates.append((best, cx, cy))
    candidates.sort(reverse=True)
    if not candidates or (len(candidates) > 1 and candidates[0][0] - candidates[1][0] < 8):
        raise ReaderError('未能唯一识别微信搜索框旁的「+」按钮。请将已登录的微信主窗口恢复为普通聊天界面。')
    return candidates[0][1:]


class WeChatReader:
    def __init__(self, cancel, evidence_dir, timeout=25):
        import uiautomation as auto
        self.auto = auto
        self.cancel = cancel
        self.evidence_dir = Path(evidence_dir)
        self.timeout = timeout
        self.note = None
        self.owned_windows = set()

    def pause(self, seconds=.3):
        import win32api
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            if win32api.GetAsyncKeyState(0x77) & 0x8000:  # F8, no keyboard hook.
                self.cancel.set()
            if self.cancel.wait(min(.05, max(0, deadline - time.monotonic()))):
                raise InterruptedError('已停止微信读取')

    def windows(self):
        import win32gui as gui
        import win32process as proc
        import win32api as api
        result = {}
        def visit(handle, _):
            if not gui.IsWindowVisible(handle):
                return
            title = gui.GetWindowText(handle)
            if not title:
                return
            try:
                _, pid = proc.GetWindowThreadProcessId(handle)
                process = api.OpenProcess(0x0400 | 0x0010, False, pid)
                try:
                    path = proc.GetModuleFileNameEx(process, 0)
                finally:
                    process.Close()
                if Path(path).name.lower() in ('weixin.exe', 'wechat.exe', 'wechatappex.exe'):
                    result[handle] = (title, Path(path).name.lower())
            except Exception:
                pass
        gui.EnumWindows(visit, None)
        return result

    def nodes(self, handle):
        root = self.auto.ControlFromHandle(handle)
        stack, count = [root], 0
        while stack and count < 2500:
            if self.cancel.is_set():
                raise InterruptedError('已停止')
            node = stack.pop()
            count += 1
            yield node
            try:
                stack.extend(reversed(node.GetChildren()))
            except Exception:
                pass

    def page_texts(self, handle):
        texts = []
        try:
            for node in self.nodes(handle):
                try:
                    if node.ControlTypeName == 'TextControl' and node.Name:
                        texts.append(node.Name)
                except Exception:
                    # Mini-program controls are replaced during page loading.
                    continue
        except InterruptedError:
            raise
        except Exception:
            pass
        return texts

    def activate(self, handle):
        import win32gui as gui
        import win32con as con
        if self.cancel.is_set():
            raise InterruptedError('已停止')
        if gui.IsIconic(handle):
            gui.PostMessage(handle, con.WM_SYSCOMMAND, con.SC_RESTORE, 0)
            self.pause(.3)
        gui.ShowWindow(handle, con.SW_RESTORE)
        # STARTUPINFO may override a process's first ShowWindow call (e.g. a
        # windowed build launched hidden); a second explicit restore honors it.
        gui.ShowWindow(handle, con.SW_RESTORE)
        self.pause(.35)
        self.auto.SwitchToThisWindow(handle)
        if handle == self.note:
            try:
                self.editor.SetFocus()
            except Exception:
                pass
        if gui.GetForegroundWindow() != handle:
            try:
                self.auto.SetForegroundWindow(handle)
            except Exception:
                # Transfer focus between input threads using the standard Win32 API.
                import win32process as proc
                import win32api as api
                current = api.GetCurrentThreadId()
                foreground, _ = proc.GetWindowThreadProcessId(gui.GetForegroundWindow())
                attached = False
                try:
                    if foreground != current:
                        proc.AttachThreadInput(current, foreground, True)
                        attached = True
                    gui.SetForegroundWindow(handle)
                except Exception as exc:
                    if gui.GetForegroundWindow() != handle:
                        raise ReaderError('无法切换微信窗口，请关闭弹窗后重试') from exc
                finally:
                    if attached:
                        proc.AttachThreadInput(current, foreground, False)
        deadline = time.monotonic() + 2
        while not self.focused(handle) and time.monotonic() < deadline:
            self.pause(.1)
        self.guard(handle)

    def focused(self, handle):
        import win32gui as gui
        current = gui.GetForegroundWindow()
        if not current:
            return False
        return (current == handle or gui.GetAncestor(current, 2) == handle
                or gui.GetAncestor(current, 3) == handle)

    def guard(self, handle):
        import win32gui as gui
        import win32api
        if win32api.GetAsyncKeyState(0x77) & 0x8000:
            self.cancel.set()
        if self.cancel.is_set():
            raise InterruptedError('已停止')
        if not self.focused(handle):
            foreground = gui.GetForegroundWindow()
            raise ReaderError(f'检测到窗口切换，已中止本项，避免误操作其他窗口（当前：{gui.GetWindowText(foreground)[:60]}）')

    def screenshot(self, handle):
        import win32gui as gui
        from PIL import ImageGrab
        self.guard(handle)
        box = gui.GetWindowRect(handle)
        return ImageGrab.grab(bbox=box, all_screens=True), box

    def prepare(self):
        candidates = self.note_editors()
        empty = [(h, editor) for h, editor in candidates if self.editor_empty(editor)]
        if len(empty) != 1:
            # Open a NEW note; never clear, reuse or overwrite a populated user note.
            self.create_note()
            def ready_note():
                found = [(h, e) for h, e in self.note_editors() if self.editor_empty(e)]
                focused = [(h, e) for h, e in found if self.focused(h)]
                if len(focused) == 1:
                    return focused[0]
                return found[0] if len(found) == 1 else None
            self.note, self.editor = self.wait_for(ready_note, '微信未打开可编辑的空白笔记。请确认未被登录或权限弹窗阻挡。')
        else:
            self.note, self.editor = empty[0]
        self.activate(self.note)

    def note_editors(self):
        candidates = []
        for handle, (_, process) in self.windows().items():
            if process != 'wechatappex.exe':
                continue
            editors = []
            for node in self.nodes(handle):
                try:
                    if node.AutomationId == 'xeditorInputId' and not node.IsOffscreen:
                        editors.append(node)
                except Exception:
                    continue
            if len(editors) == 1:
                candidates.append((handle, editors[0]))
        return candidates

    def editor_empty(self, editor):
        try:
            value = editor.GetPattern(self.auto.PatternId.ValuePattern)
            if value is None:
                return False
            return not editor.GetValuePattern().Value.strip()
        except Exception:
            return False

    def create_note(self):
        main = [h for h, (title, process) in self.windows().items()
                if title == '微信' and process in ('weixin.exe', 'wechat.exe')]
        if len(main) != 1:
            raise ReaderError('未找到唯一的电脑版微信主窗口，请先打开并登录微信。')
        handle = main[0]
        self.activate(handle)
        image, bounds = self.screenshot(handle)
        x, y = find_new_note_button(image)
        self.guard(handle)
        self.auto.Click(bounds[0] + x, bounds[1] + y)
        self.pause(.3)
        self.click_text(handle, '写笔记')
        self.pause(.7)

    def wait_for(self, finder, message):
        deadline = time.monotonic() + self.timeout
        while time.monotonic() < deadline:
            value = finder()
            if value:
                return value
            self.pause(.25)
        raise ReaderError(message)

    def viewer_code(self, handle, payload):
        import zxingcpp
        image, box = self.screenshot(handle)
        found = zxingcpp.read_barcodes(image)
        if len(found) != 1 or found[0].text != payload:
            raise ReaderError('微信预览中的二维码与当前任务不一致，已拒绝读取')
        p = found[0].position
        return box[0] + (p.top_left.x + p.bottom_right.x) // 2, box[1] + (p.top_left.y + p.bottom_right.y) // 2

    def recognize_menu(self, handle):
        self.click_text(handle, '识别图中二维码')

    def click_text(self, handle, label):
        import numpy as np
        from table_audit import ocr_engine
        image, box = self.screenshot(handle)
        found, _ = ocr_engine()(np.asarray(image))
        matches = [b for b, text, score in found or [] if label in text.replace(' ', '') and score > .7]
        if len(matches) != 1:
            raise ReaderError(f'未找到唯一的微信「{label}」菜单；当前界面可能被遮挡或版本不兼容')
        b = matches[0]
        self.guard(handle)
        self.auto.Click(round(box[0] + sum(p[0] for p in b) / 4), round(box[1] + sum(p[1] for p in b) / 4))

    def read(self, payload, sequence):
        import win32gui as gui
        import win32con as con
        import zxingcpp
        if self.note is None:
            self.prepare()
        self.evidence_dir.mkdir(parents=True, exist_ok=True)
        qr_path = self.evidence_dir / f'{sequence:04d}-qr.png'
        qr_image(payload).save(qr_path)
        before = set(self.windows())
        self.activate(self.note)
        self.editor.SetFocus()
        self.guard(self.note)
        self.auto.SendKeys('{Ctrl}{End}{Enter}', waitTime=.1)
        copy_qr(payload)
        self.guard(self.note)
        self.auto.SendKeys('{Ctrl}v', waitTime=.2)
        self.pause(.6)
        image, bounds = self.screenshot(self.note)
        matches = [c for c in zxingcpp.read_barcodes(image) if c.text == payload]
        if len(matches) != 1:
            raise ReaderError('笔记内未找到唯一的当前二维码，请放大笔记窗口后重试')
        p = matches[0].position
        self.guard(self.note)
        x = bounds[0] + (p.top_left.x + p.bottom_right.x) // 2
        y = bounds[1] + (p.top_left.y + p.bottom_right.y) // 2
        self.auto.Click(x, y, waitTime=.08)
        # Some WeChat versions open embedded note images with a single click.
        focused = gui.GetForegroundWindow()
        if self.focused(self.note):
            self.auto.Click(x, y, waitTime=.1)
        elif any(t == '图片和视频' and self.focused(h) for h, (t, _) in self.windows().items()):
            pass
        else:
            raise ReaderError('打开图片时窗口发生意外切换，已停止')
        def new_viewer():
            candidates = [h for h, (t, _) in self.windows().items() if t == '图片和视频' and self.focused(h)]
            return candidates[0] if len(candidates) == 1 else None
        viewer = self.wait_for(new_viewer, '未打开新的微信图片预览；请关闭旧图片预览后重试')
        self.owned_windows.add(viewer)
        self.activate(viewer)
        x, y = self.viewer_code(viewer, payload)
        baseline = set(self.windows())
        self.guard(viewer)
        self.auto.RightClick(x, y)
        self.pause(.3)
        self.recognize_menu(viewer)
        def new_page():
            candidates = [h for h, (_, process) in self.windows().items()
                          if h not in baseline and process == 'wechatappex.exe' and h != self.note]
            if len(candidates) > 1:
                raise ReaderError('出现多个新微信窗口，无法确认当前码对应的页面')
            return candidates[0] if candidates else None
        page = self.wait_for(new_page, '没有打开新的点餐小程序；可能需要手机微信、登录或手动授权')
        self.owned_windows.add(page)
        self.activate(page)
        last_table, stable = '', 0
        deadline = time.monotonic() + self.timeout
        while time.monotonic() < deadline:
            self.guard(page)
            texts = self.page_texts(page)
            try:
                table = parse_table(texts)
            except ReaderError:
                table = ''
            stable = stable + 1 if table and table == last_table else 0
            last_table = table
            if table and stable >= 1:
                self.evidence_dir.mkdir(parents=True, exist_ok=True)
                evidence = self.evidence_dir / f'{sequence:04d}.png'
                self.screenshot(page)[0].save(evidence)
                title = gui.GetWindowText(page)
                (self.evidence_dir / f'{sequence:04d}.json').write_text(json.dumps({
                    'payload': payload, 'table': table, 'app': title,
                    'page_screenshot': str(evidence), 'single_qr': str(qr_path),
                    'read_at': time.strftime('%Y-%m-%dT%H:%M:%S%z'),
                }, ensure_ascii=False, indent=2), encoding='utf-8')
                gui.PostMessage(page, con.WM_CLOSE, 0, 0)
                self.wait_for(lambda: not gui.IsWindow(page) or not gui.IsWindowVisible(page), '点餐窗口未关闭，已中止以防串台')
                gui.PostMessage(viewer, con.WM_CLOSE, 0, 0)
                self.wait_for(lambda: not gui.IsWindow(viewer) or not gui.IsWindowVisible(viewer), '图片预览未关闭，已中止以防串码')
                self.owned_windows.clear()
                return LiveResult(table, title, str(evidence))
            self.pause(.5)
        raise ReaderError('点餐页面未显示可读取的桌号，已保留页面；未选择人数或执行点餐')

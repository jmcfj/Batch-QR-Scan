"""Manual preparation and one-time table-position selection dialogs."""
import tkinter as tk
from tkinter import ttk
from PIL import ImageTk
from reading_profiles import (ReadingProfile, RegionReadError, selected_texts,
                              interpret_texts, read_ocr, value_kind, validate_rect)


class PreparationDialog(ttk.Frame):
    """Persistent main-window guide; no modal window or focus grab."""
    def __init__(self, parent, count, ready, cancel):
        super().__init__(parent, padding=16)
        from pathlib import Path
        from PIL import Image
        self.heading = tk.StringVar(value='扫描完成后，请按以下图示准备微信')
        ttk.Label(self, textvariable=self.heading, font=('Microsoft YaHei UI', 16, 'bold')).pack(anchor='w', pady=(0, 8))
        illustrations = ttk.Frame(self)
        illustrations.pack(fill='x')
        self.photos = []
        assets = Path(__file__).resolve().parent / 'assets'
        for filename, caption in [
            ('wechat-note-menu.png', '① 微信右上角「+」→「写笔记」'),
            ('wechat-note-pin.png', '② 置顶空白笔记，再最小化微信主窗口')]:
            column = ttk.Frame(illustrations)
            column.pack(side='left', fill='both', expand=True, padx=8)
            ttk.Label(column, text=caption, font=('Microsoft YaHei UI', 11, 'bold')).pack(anchor='w')
            with Image.open(assets / filename) as source:
                image = source.copy()
            image.thumbnail((260, 140))
            photo = ImageTk.PhotoImage(image, master=self)
            self.photos.append(photo)
            ttk.Label(column, image=photo).pack(anchor='w', pady=6)
        ttk.Label(self, text='新建一个空白笔记后，最小化微信主窗口，只保留笔记窗口在当前桌面。\n笔记窗口顶部有图钉「置顶」按钮（如图红箭头），请点击置顶。\n准备期间可以切换窗口；完成后返回这里，点击下方开始读取。', wraplength=760, justify='left').pack(anchor='w', pady=6)
        tk.Label(self, text='开始读取后：不要动鼠标、键盘，不要切换窗口！\n首次打开某个餐厅的小程序时，请在位置引导中框选「桌台号」所在区域。\n仅框选时可以操作鼠标；确认后自动沿用该位置，直到整批完成。\nF8 停止；意外切换窗口会暂停，可点「继续读取」。', bg='#fff1ce', fg='#7a4700', font=('Microsoft YaHei UI', 11, 'bold'), justify='left', anchor='w', padx=12, pady=6).pack(fill='x', pady=6)
        actions = ttk.Frame(self)
        actions.pack(fill='x')
        self.cancel_button = ttk.Button(actions, text='暂不读取，查看扫码结果', command=cancel)
        self.cancel_button.pack(side='left')
        self.ready_button = ttk.Button(actions, text='笔记已置顶、微信已最小化，开始读取', command=ready, style='Accent.TButton')
        self.ready_button.pack(side='right')
        self.disable()
        if count:
            self.set_count(count)

    def set_count(self, count):
        self.heading.set(f'已识别 {count} 个网址桌台码 · 请先完成微信准备')
        self.ready_button.configure(state='normal')
        self.cancel_button.configure(state='normal')

    def disable(self):
        self.ready_button.configure(state='disabled')
        self.cancel_button.configure(state='disabled')


class RegionPicker(tk.Toplevel):
    def __init__(self, parent, ticket, complete):
        super().__init__(parent)
        self.title('首次引导：请框出台号读取位置')
        self.transient(parent)
        self.attributes('-topmost', True)
        self.resizable(False, False)
        self.ticket, self.complete = ticket, complete
        self.rect = None
        self.profile = None
        self.start_point = None
        image = ticket['image']
        maximum = (min(1100, self.winfo_screenwidth() - 100), max(220, min(760, self.winfo_screenheight() - 260)))
        display = image.copy()
        display.thumbnail(maximum)
        self.dw, self.dh = display.size
        self.photo = ImageTk.PhotoImage(display, master=self)
        frame = ttk.Frame(self, padding=12)
        frame.pack(fill='both', expand=True)
        ttk.Label(frame, text=ticket['label'], font=('Microsoft YaHei UI', 11, 'bold'), wraplength=max(360, self.dw)).pack(anchor='w')
        ttk.Label(frame, text='拖框选择「桌号：A1」这一小块区域，尽量包含标签；也可只框 A1。\n确认后将记住此系统的位置，后续自动读取。', wraplength=max(360, self.dw)).pack(anchor='w', pady=8)
        self.canvas = tk.Canvas(frame, width=self.dw, height=self.dh, highlightthickness=0, cursor='crosshair')
        self.canvas.pack()
        self.canvas.create_image(0, 0, anchor='nw', image=self.photo)
        self.canvas.bind('<ButtonPress-1>', self.begin)
        self.canvas.bind('<B1-Motion>', self.drag)
        self.canvas.bind('<ButtonRelease-1>', self.finish_selection)
        self.feedback = tk.StringVar(value='尚未选择区域')
        ttk.Label(frame, textvariable=self.feedback, wraplength=max(360, self.dw)).pack(anchor='w', pady=8)
        actions = ttk.Frame(frame)
        actions.pack(fill='x')
        ttk.Button(actions, text='取消本批', command=lambda: self.finish(None)).pack(side='left')
        ttk.Button(actions, text='页面未加载，重新截图', command=lambda: self.finish('refresh')).pack(side='left', padx=8)
        self.confirm = ttk.Button(actions, text='确认台号位置，继续整批', state='disabled', style='Accent.TButton', command=lambda: self.finish(self.profile))
        self.confirm.pack(side='right')
        self.protocol('WM_DELETE_WINDOW', lambda: self.finish(None))
        self.grab_set()

    def point(self, event):
        return max(0, min(self.dw, event.x)), max(0, min(self.dh, event.y))

    def begin(self, event):
        self.start_point = self.point(event)
        self.canvas.delete('selection')
        self.profile = None
        self.confirm.configure(state='disabled')

    def drag(self, event):
        if self.start_point:
            x, y = self.point(event)
            self.canvas.delete('selection')
            self.canvas.create_rectangle(*self.start_point, x, y, outline='#f04438', width=2, tags='selection')

    def finish_selection(self, event):
        if not self.start_point:
            return
        x, y = self.point(event)
        a, b = self.start_point
        self.rect = (min(a, x) / self.dw, min(b, y) / self.dh, max(a, x) / self.dw, max(b, y) / self.dh)
        try:
            validate_rect(self.rect)
            try:
                value, anchor = interpret_texts(selected_texts(self.ticket['regions'], self.rect))
            except RegionReadError:
                value, anchor, _ = read_ocr(self.ticket['image'], self.rect)
            self.profile = ReadingProfile(self.ticket['key'], self.ticket['label'], self.rect,
                                          self.ticket['image'].width / self.ticket['image'].height,
                                          value_kind(value), anchor)
            self.feedback.set(f'当前区域读到台号：{value}。确认无误后，继续整批读取。')
            self.confirm.configure(state='normal')
        except Exception as exc:
            self.feedback.set(f'未确认：{exc}。请重新框选，尽量包含「桌号」标签。')
            self.confirm.configure(state='disabled')

    def finish(self, result):
        self.destroy()
        self.complete(result)

"""Manual preparation and one-time table-position selection dialogs."""
import tkinter as tk
from tkinter import ttk
from PIL import ImageTk
from reading_profiles import (ReadingProfile, RegionReadError, selected_texts,
                              interpret_texts, read_ocr, value_kind, validate_rect)


class PreparationDialog(tk.Toplevel):
    def __init__(self, parent, count, ready, cancel):
        super().__init__(parent)
        self.title('开始读取前，请准备微信')
        self.transient(parent)
        self.resizable(False, False)
        body = ttk.Frame(self, padding=24)
        body.pack(fill='both', expand=True)
        ttk.Label(body, text=f'已识别 {count} 个网址桌台码', font=('Microsoft YaHei UI', 16, 'bold')).pack(anchor='w', pady=(0, 16))
        ttk.Label(body, text='1. 请手动在电脑版微信点击「+ → 写笔记」，新建一个空白笔记。\n\n2. 准备好后返回这里，点击下方「笔记已准备，开始读取」。\n\n3. 首次遇到一个餐厅系统，会展示点餐页截图，请框出台号位置。\n   确认一次后会保存模板，后续同类页面自动读取。', justify='left').pack(anchor='w')
        tk.Label(body, text='开始自动读取后，请勿切换窗口或操作鼠标、键盘。\n位置引导弹出时可以操作该引导；确认后请等待整批完成。\nF8 可停止。意外切走会暂停，可点击「继续读取」。', bg='#fff1ce', fg='#7a4700', justify='left', padx=12, pady=12).pack(fill='x', pady=18)
        buttons = ttk.Frame(body)
        buttons.pack(fill='x')
        def finish(callback):
            self.destroy()
            callback()
        ttk.Button(buttons, text='暂不读取，保留扫码结果', command=lambda: finish(cancel)).pack(side='left')
        ttk.Button(buttons, text='笔记已准备，开始读取', style='Accent.TButton', command=lambda: finish(ready)).pack(side='right', padx=(14, 0))
        self.protocol('WM_DELETE_WINDOW', lambda: finish(cancel))
        self.grab_set()


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

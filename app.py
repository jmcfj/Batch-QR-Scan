"""Batch QR Scan Windows desktop application."""
from pathlib import Path
from queue import Queue, Empty
from threading import Thread, Event
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

from scanner import SUPPORTED, scan_file, export_results


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title('Batch QR Scan · 批量扫码')
        self.geometry('1180x760')
        self.minsize(900, 600)
        self.configure(bg='#f3f5f9')
        self.files, self.results = [], []
        self.events = Queue()
        self.cancel = Event()
        self.running = False
        style = ttk.Style(self)
        style.theme_use('clam')
        style.configure('.', font=('Microsoft YaHei UI', 10))
        style.configure('Treeview', rowheight=32, background='white', fieldbackground='white')
        style.configure('Treeview.Heading', font=('Microsoft YaHei UI', 10, 'bold'), padding=8)
        style.configure('TButton', padding=(12, 8))
        style.configure('Accent.TButton', foreground='white', background='#315bdf')
        header = tk.Frame(self, bg='#16233d', padx=26, pady=20)
        header.pack(fill='x')
        tk.Label(header, text='▦  Batch QR Scan', font=('Microsoft YaHei UI', 24, 'bold'), fg='white', bg='#16233d').pack(anchor='w')
        tk.Label(header, text='批量识别图片与 PDF 中的二维码 / 条形码 · 本地处理', fg='#becbe5', bg='#16233d', font=('Microsoft YaHei UI', 11)).pack(anchor='w', pady=(6, 0))
        toolbar = ttk.Frame(self, padding=(20, 16))
        toolbar.pack(fill='x')
        self.mutable = []
        for label, command in [('添加文件', self.add_files), ('添加文件夹', self.add_folder), ('粘贴截图', self.paste_image), ('清空任务', self.clear)]:
            button = ttk.Button(toolbar, text=label, command=command)
            button.pack(side='left', padx=(0, 8))
            self.mutable.append(button)
        self.start_button = ttk.Button(toolbar, text='开始扫描', command=self.start, style='Accent.TButton')
        self.start_button.pack(side='right')
        self.stop_button = ttk.Button(toolbar, text='停止', command=self.stop, state='disabled')
        self.stop_button.pack(side='right', padx=8)
        body = ttk.Panedwindow(self, orient='horizontal')
        body.pack(fill='both', expand=True, padx=20)
        left = ttk.Frame(body, padding=12)
        right = ttk.Frame(body, padding=12)
        body.add(left, weight=1)
        body.add(right, weight=4)
        self.file_count = tk.StringVar(value='待扫描文件 · 0')
        ttk.Label(left, textvariable=self.file_count, font=('Microsoft YaHei UI', 12, 'bold')).pack(anchor='w', pady=(0, 10))
        self.file_list = tk.Listbox(left, width=28, height=8, borderwidth=0, font=('Microsoft YaHei UI', 10), selectmode='extended')
        self.file_list.pack(fill='both', expand=True)
        self.file_list.bind('<Delete>', self.remove_files)
        ttk.Label(left, text='选中文件按 Delete 移除\n文件夹将递归导入；支持多页 TIFF', foreground='#667085').pack(anchor='w', pady=10)
        filters = ttk.Frame(right)
        filters.pack(fill='x', pady=(0, 10))
        ttk.Label(filters, text='识别结果', font=('Microsoft YaHei UI', 12, 'bold')).pack(side='left')
        self.query = tk.StringVar()
        ttk.Entry(filters, textvariable=self.query, width=22).pack(side='right', padx=8)
        ttk.Label(filters, text='搜索').pack(side='right')
        self.only_codes = tk.BooleanVar()
        ttk.Checkbutton(filters, text='仅已识别', variable=self.only_codes, command=self.refresh).pack(side='right', padx=12)
        self.query.trace_add('write', lambda *_: self.refresh())
        table = ttk.Frame(right)
        table.pack(fill='both', expand=True)
        cols = ('source', 'page', 'status', 'format', 'text')
        self.table = ttk.Treeview(table, columns=cols, height=8, show='headings', selectmode='extended')
        for key, label, width in zip(cols, ['来源文件', '页码', '状态', '码类型', '识别内容'], [170, 55, 85, 100, 320]):
            self.table.heading(key, text=label)
            self.table.column(key, width=width, minwidth=50, stretch=key in ('source', 'text'))
        sy = ttk.Scrollbar(table, orient='vertical', command=self.table.yview)
        sx = ttk.Scrollbar(table, orient='horizontal', command=self.table.xview)
        self.table.configure(yscrollcommand=sy.set, xscrollcommand=sx.set)
        self.table.grid(row=0, column=0, sticky='nsew')
        sy.grid(row=0, column=1, sticky='ns')
        sx.grid(row=1, column=0, sticky='ew')
        table.rowconfigure(0, weight=1)
        table.columnconfigure(0, weight=1)
        self.table.bind('<<TreeviewSelect>>', self.details)
        self.table.bind('<Control-c>', lambda _: self.copy())
        self.detail = tk.Text(right, height=4, wrap='word', font=('Microsoft YaHei UI', 10), relief='flat', state='disabled')
        self.detail.pack(fill='x', pady=(10, 0))
        actions = ttk.Frame(right)
        actions.pack(fill='x', pady=(10, 0))
        ttk.Button(actions, text='复制选中内容', command=self.copy).pack(side='left')
        ttk.Button(actions, text='导出全部 CSV / JSON', command=self.export).pack(side='right')
        footer = ttk.Frame(self, padding=20)
        footer.pack(fill='x')
        self.status = tk.StringVar(value='就绪 · 添加文件、文件夹，或复制截图后点击「粘贴截图」')
        ttk.Label(footer, textvariable=self.status).pack(anchor='w')
        self.progress = ttk.Progressbar(footer, mode='determinate')
        self.progress.pack(fill='x', pady=(10, 0))
        self.protocol('WM_DELETE_WINDOW', self.close)
        self.after(80, self.poll)

    def add(self, paths):
        known = {str(p).casefold() for p in self.files}
        for path in paths:
            path = Path(path).resolve()
            if path.suffix.lower() in SUPPORTED and str(path).casefold() not in known:
                self.files.append(path)
                known.add(str(path).casefold())
                self.file_list.insert('end', path.name)
        self.file_count.set(f'待扫描文件 · {len(self.files)}')

    def add_files(self):
        self.add(filedialog.askopenfilenames(filetypes=[('图片与 PDF', ' '.join('*' + ext for ext in sorted(SUPPORTED))), ('所有文件', '*.*')]))

    def add_folder(self):
        folder = filedialog.askdirectory()
        if folder:
            try:
                self.add(sorted(Path(folder).rglob('*')))
            except OSError as exc:
                messagebox.showerror('无法读取文件夹', str(exc))

    def paste_image(self):
        from PIL import ImageGrab, Image
        import tempfile
        try:
            data = ImageGrab.grabclipboard()
            if isinstance(data, Image.Image):
                if not hasattr(self, 'clipboard_dir'):
                    self.clipboard_dir = tempfile.TemporaryDirectory(prefix='batchqr-')
                path = Path(self.clipboard_dir.name) / f'截图-{len(self.files) + 1}.png'
                data.save(path)
                self.add([path])
            elif isinstance(data, list):
                self.add(data)
            else:
                messagebox.showinfo('粘贴截图', '请先使用 Win + Shift + S 截图，或复制图片文件。')
        except Exception as exc:
            messagebox.showerror('粘贴失败', str(exc))

    def remove_files(self, _=None):
        if self.running:
            return
        for i in reversed(self.file_list.curselection()):
            del self.files[i]
            self.file_list.delete(i)
        self.file_count.set(f'待扫描文件 · {len(self.files)}')

    def clear(self):
        self.files.clear()
        self.results.clear()
        self.file_list.delete(0, 'end')
        self.file_count.set('待扫描文件 · 0')
        self.refresh()
        self.progress['value'] = 0
        self.status.set('已清空')

    def start(self):
        if self.running or not self.files:
            return
        self.running = True
        self.cancel.clear()
        self.results.clear()
        self.refresh()
        for button in self.mutable + [self.start_button]:
            button.configure(state='disabled')
        self.stop_button.configure(state='normal')
        self.progress.configure(maximum=len(self.files), value=0)
        Thread(target=self.worker, args=(tuple(self.files),), daemon=True).start()

    def worker(self, files):
        try:
            for index, path in enumerate(files):
                if self.cancel.is_set():
                    break
                self.events.put(('status', f'扫描中 · {index + 1}/{len(files)} · {path.name}'))
                for rows in scan_file(path, self.cancel):
                    self.events.put(('rows', rows))
                self.events.put(('progress', index + 1))
        finally:
            self.events.put(('done', None))

    def stop(self):
        self.cancel.set()
        self.status.set('正在停止 · 等待当前页处理结束')
        self.stop_button.configure(state='disabled')

    def poll(self):
        changed = False
        try:
            for _ in range(200):
                kind, value = self.events.get_nowait()
                if kind == 'rows':
                    self.results.extend(value)
                    changed = True
                elif kind == 'status':
                    self.status.set(value)
                elif kind == 'progress':
                    self.progress['value'] = value
                elif kind == 'done':
                    self.running = False
                    for button in self.mutable + [self.start_button]:
                        button.configure(state='normal')
                    self.stop_button.configure(state='disabled')
                    count = sum(r.status == '已识别' for r in self.results)
                    failed = sum(r.status == '失败' for r in self.results)
                    prefix = '已停止' if self.cancel.is_set() else '扫描完成'
                    self.status.set(f'{prefix} · 识别 {count} 个码 · 失败 {failed} 项 · 共 {len(self.results)} 条记录')
        except Empty:
            pass
        if changed:
            self.refresh()
        self.after(80, self.poll)

    def refresh(self):
        self.table.delete(*self.table.get_children())
        query = self.query.get().casefold()
        for index, row in enumerate(self.results):
            if self.only_codes.get() and row.status != '已识别':
                continue
            if query and query not in f'{row.source} {row.text} {row.format} {row.status}'.casefold():
                continue
            self.table.insert('', 'end', iid=str(index), values=(Path(row.source).name, row.page, row.status, row.format, row.text))

    def details(self, _=None):
        selected = self.table.selection()
        self.detail.configure(state='normal')
        self.detail.delete('1.0', 'end')
        if selected:
            row = self.results[int(selected[0])]
            self.detail.insert('end', f'{row.source} · 第 {row.page} 页\n{row.text}\n位置：{row.position}')
        self.detail.configure(state='disabled')

    def copy(self):
        selected = self.table.selection()
        if selected:
            self.clipboard_clear()
            self.clipboard_append('\n'.join(self.results[int(i)].text for i in selected))

    def export(self):
        if not self.results:
            messagebox.showinfo('导出', '请先扫描文件。')
            return
        path = filedialog.asksaveasfilename(defaultextension='.csv', initialfile='扫码结果.csv', filetypes=[('CSV 表格', '*.csv'), ('JSON 数据', '*.json')])
        if path:
            try:
                export_results(path, self.results)
                messagebox.showinfo('导出完成', f'已导出 {len(self.results)} 条记录。')
            except OSError as exc:
                messagebox.showerror('导出失败', str(exc))

    def close(self):
        if self.running:
            self.stop()
            self.after(100, self.finish_close)
        else:
            self.destroy()

    def finish_close(self):
        if self.running:
            self.after(100, self.finish_close)
        else:
            self.destroy()


if __name__ == '__main__':
    App().mainloop()

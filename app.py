"""Batch QR Scan Windows desktop application."""
from pathlib import Path
from queue import Queue, Empty
from threading import Thread, Event
import webbrowser
import csv
import os
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

from scanner import SUPPORTED, scan_file, export_results
from links import web_url
from table_audit import apply_reference, compare_table, load_reference, load_reference_folder, read_reference_state, save_reference_state


class App(tk.Tk):
    def __init__(self, settings_path=None):
        super().__init__()
        self.title('Batch QR Scan · 批量扫码')
        self.geometry('1320x850')
        self.minsize(1000, 680)
        self.configure(bg='#f3f5f9')
        self.files, self.results = [], []
        self.events = Queue()
        self.cancel = Event()
        self.running = False
        self.settings_path = Path(settings_path) if settings_path else Path(os.environ.get('LOCALAPPDATA', str(Path.home()))) / 'BatchQRScan' / 'reference.json'
        self.reference, self.reference_evidence = read_reference_state(self.settings_path)
        self.audit_enabled = True
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
        tk.Label(header, text='餐厅桌台码核对 · 逐个对应印刷台号、二维码及实际台号', fg='#becbe5', bg='#16233d', font=('Microsoft YaHei UI', 11)).pack(anchor='w', pady=(6, 0))
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
        self.live_button = ttk.Button(toolbar, text='微信实读（试验）', command=self.start_live, style='Accent.TButton')
        self.live_button.pack(side='left', padx=8)
        self.mutable.append(self.live_button)
        body = ttk.Panedwindow(self, orient='horizontal')
        body.pack(fill='both', expand=True, padx=20)
        left = ttk.Frame(body, padding=12)
        right = ttk.Frame(body, padding=12)
        body.add(left, weight=1)
        body.add(right, weight=4)
        self.file_count = tk.StringVar(value='待扫描文件 · 0')
        ttk.Label(left, textvariable=self.file_count, font=('Microsoft YaHei UI', 12, 'bold')).pack(anchor='w', pady=(0, 10))
        self.audit_mode = tk.BooleanVar(value=True)
        self.audit_toggle = ttk.Checkbutton(left, text='识别码上方的印刷台号', variable=self.audit_mode)
        self.audit_toggle.pack(anchor='w', pady=(0, 8))
        self.mutable.append(self.audit_toggle)
        original_button = ttk.Button(left, text='导入后台原始码文件夹', command=self.import_original_folder, style='Accent.TButton')
        original_button.pack(fill='x', pady=(0, 8))
        self.mutable.append(original_button)
        reference_button = ttk.Button(left, text='导入实际台号对照 CSV', command=self.import_reference)
        reference_button.pack(fill='x', pady=(0, 8))
        self.mutable.append(reference_button)
        self.reference_label = tk.StringVar(value='未导入对照 · 实际台号待核实')
        if self.reference:
            self.reference_label.set(f'已记住 {len(self.reference)} 个实际台号')
        ttk.Label(left, textvariable=self.reference_label, wraplength=240).pack(anchor='w', pady=(0, 8))
        ttk.Label(left, text='微信实读（试验）：\n先扫描文件，再在微信「+ → 写笔记」\n新建空白笔记，保持打开。\n点击「微信实读（试验）」。\n读取期间请勿操作微信或鼠标。\nF8 停止；窗口切换时中止本项。', wraplength=240, foreground='#315bdf').pack(anchor='w', pady=(0, 8))
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
        cols = ('source', 'page', 'printed_table', 'actual_table', 'table_check', 'live_status', 'text', 'table_id', 'status', 'format')
        self.table = ttk.Treeview(table, columns=cols, height=8, show='headings', selectmode='extended')
        for key, label, width in zip(cols, ['来源文件', '页码', '印刷台号', '实际台号', '核对结果', '微信读取状态', '二维码原文', '内部桌台 ID', '扫码状态', '码类型'], [120, 50, 90, 90, 175, 185, 240, 210, 90, 100]):
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
        self.table.bind('<Double-1>', self.open_clicked_webpage)
        self.table.bind('<Return>', lambda _: self.open_webpage())
        self.table.tag_configure('mismatch', background='#ffe4e4', foreground='#9b1c1c')
        self.table.tag_configure('pending', background='#fff5d6')
        self.table.tag_configure('match', background='#e5f6eb')
        self.detail = tk.Text(right, height=4, wrap='word', font=('Microsoft YaHei UI', 10), relief='flat', state='disabled')
        self.detail.pack(fill='x', pady=(10, 0))
        actions = ttk.Frame(right)
        actions.pack(fill='x', pady=(10, 0))
        ttk.Button(actions, text='复制选中内容', command=self.copy).pack(side='left')
        self.open_button = ttk.Button(actions, text='打开网页', command=self.open_webpage, state='disabled')
        self.open_button.pack(side='left', padx=8)
        self.auto_open = tk.BooleanVar(value=False)
        ttk.Checkbutton(actions, text='扫描后打开首个网页', variable=self.auto_open).pack(side='left')
        ttk.Button(actions, text='导出全部 CSV / JSON', command=self.export).pack(side='right')
        footer = ttk.Frame(self, padding=20)
        footer.pack(side='bottom', fill='x', before=body)
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
        self.audit_enabled = self.audit_mode.get()
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
                for rows in scan_file(path, self.cancel, audit=self.audit_enabled):
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
                    if self.audit_enabled or self.reference:
                        for row in value:
                            apply_reference(row, self.reference, self.reference_evidence)
                    self.results.extend(value)
                    changed = True
                elif kind == 'status':
                    self.status.set(value)
                elif kind == 'progress':
                    self.progress['value'] = value
                elif kind == 'live_row':
                    indices, result = value
                    for i in indices:
                        row = self.results[i]
                        row.actual_table = result.table
                        row.table_evidence = f'微信实际页面：{result.app}'
                        row.live_evidence = result.evidence
                        row.live_status = '已读取'
                        compare_table(row)
                    changed = True
                elif kind == 'live_fail':
                    indices, reason = value
                    for i in indices:
                        self.results[i].live_status = f'读取失败：{reason}'
                    changed = True
                elif kind == 'live_done':
                    self.running = False
                    for button in self.mutable + [self.start_button]:
                        button.configure(state='normal')
                    self.stop_button.configure(state='disabled')
                    for row in self.results:
                        if row.live_status == '等待微信读取':
                            row.live_status = '未执行：已停止或前项失败'
                    count = sum(r.live_status == '已读取' for r in self.results)
                    self.status.set(f'微信读取结束 · 实际读取 {count} 条 · {value or "完成"}')
                    changed = True
                elif kind == 'done':
                    self.running = False
                    for button in self.mutable + [self.start_button]:
                        button.configure(state='normal')
                    self.stop_button.configure(state='disabled')
                    count = sum(r.status == '已识别' for r in self.results)
                    failed = sum(r.status == '失败' for r in self.results)
                    prefix = '已停止' if self.cancel.is_set() else '扫描完成'
                    self.status.set(f'{prefix} · 识别 {count} 个码 · 失败 {failed} 项 · 共 {len(self.results)} 条记录')
                    if self.audit_enabled:
                        matches = sum(r.table_check == '一致' for r in self.results)
                        mismatches = sum(r.table_check == '不一致' for r in self.results)
                        pending = count - matches - mismatches
                        self.status.set(f'{prefix} · {count} 个码 · 一致 {matches} · 不一致 {mismatches} · 待核实 {pending} · 失败 {failed}')
                    if not self.cancel.is_set() and self.auto_open.get():
                        first = next((r for r in self.results if r.status == '已识别' and web_url(r.text)), None)
                        if first is not None:
                            self.launch_url(web_url(first.text))
        except Empty:
            pass
        if changed:
            self.refresh()
        self.after(80, self.poll)

    def refresh(self):
        self.table.delete(*self.table.get_children())
        self.details()
        query = self.query.get().casefold()
        for index, row in enumerate(self.results):
            if self.only_codes.get() and row.status != '已识别':
                continue
            if query and query not in f'{row.source} {row.text} {row.format} {row.status} {row.printed_table} {row.actual_table} {row.table_id} {row.table_check}'.casefold():
                continue
            tag = 'match' if row.table_check == '一致' else ('mismatch' if row.table_check == '不一致' else 'pending')
            self.table.insert('', 'end', iid=str(index), values=(Path(row.source).name, row.page, row.printed_table or '未读到', row.actual_table or '未取得', row.table_check, row.live_status, row.text, row.table_id, row.status, row.format), tags=(tag,))

    def details(self, _=None):
        selected = self.table.selection()
        self.detail.configure(state='normal')
        self.detail.delete('1.0', 'end')
        self.open_button.configure(state='disabled')
        if selected:
            row = self.results[int(selected[0])]
            url = web_url(row.text) if row.status == '已识别' else None
            if url:
                self.open_button.configure(state='normal')
            hint = '网址二维码 · 点击「打开网页」或双击此行查看网页内容' if url else f'位置：{row.position}'
            self.detail.insert('end', f'{row.source} · 第 {row.page} 页\n印刷：{row.printed_table or "未读到"} / 实际：{row.actual_table or "未取得"} / {row.table_check}\n依据：{row.table_evidence or "没有独立台号依据，内部 ID 不代表实际台号"}\n微信：{row.live_status}  截图：{row.live_evidence}\n{row.text}\n{hint}')
        self.detail.configure(state='disabled')

    def open_clicked_webpage(self, event):
        item = self.table.identify_row(event.y)
        if item:
            self.table.selection_set(item)
            self.open_webpage()

    def open_webpage(self):
        selected = self.table.selection()
        if selected:
            row = self.results[int(selected[0])]
            url = web_url(row.text) if row.status == '已识别' else None
            if url:
                self.launch_url(url)

    def launch_url(self, url):
        try:
            if not webbrowser.open(url, new=2):
                raise OSError('系统未能启动默认浏览器，请复制网址手动打开。')
        except Exception as exc:
            messagebox.showerror('打开网页失败', str(exc))

    def copy(self):
        selected = self.table.selection()
        if selected:
            self.clipboard_clear()
            self.clipboard_append('\n'.join(self.results[int(i)].text for i in selected))

    def import_reference(self):
        path = filedialog.askopenfilename(title='选择独立的实际台号清单（不要用待检查图片自行生成）', filetypes=[('CSV 台号清单', '*.csv')])
        if not path:
            return
        try:
            reference = load_reference(path)
        except (OSError, ValueError, csv.Error) as exc:
            messagebox.showerror('导入失败', str(exc))
            return
        self.set_reference(reference, f'独立 CSV 清单：{Path(path).name}')

    def start_live(self):
        if self.running:
            return
        groups = {}
        for i, row in enumerate(self.results):
            if row.status == '已识别' and web_url(row.text):
                groups.setdefault(row.text, []).append(i)
        if not groups:
            messagebox.showinfo('微信读取台号', '请先添加排版图或 PDF，并扫描出包含网址的桌台码。')
            return
        self.cancel.clear()
        self.running = True
        for button in self.mutable + [self.start_button]:
            button.configure(state='disabled')
        self.stop_button.configure(state='normal')
        for indices in groups.values():
            for i in indices:
                row = self.results[i]
                row.live_status = '等待微信读取'
                row.actual_table = row.table_evidence = row.live_evidence = ''
                compare_table(row)
        self.refresh()
        self.progress.configure(maximum=len(groups), value=0)
        Thread(target=self.live_worker, args=(groups,), daemon=True).start()

    def live_worker(self, groups):
        from datetime import datetime
        from uuid import uuid4
        reason = ''
        active = []
        try:
            import uiautomation as auto
            from wechat_reader import WeChatReader
            evidence_dir = self.settings_path.parent / 'evidence' / (datetime.now().strftime('%Y%m%d-%H%M%S') + '-' + uuid4().hex[:8])
            with auto.UIAutomationInitializerInThread():
                reader = WeChatReader(self.cancel, evidence_dir)
                reader.prepare()
                for sequence, (payload, indices) in enumerate(groups.items(), 1):
                    active = indices
                    if self.cancel.is_set():
                        raise InterruptedError('已停止')
                    self.events.put(('status', f'微信实读 {sequence}/{len(groups)} · 请勿操作微信或鼠标'))
                    result = reader.read(payload, sequence)
                    self.events.put(('live_row', (indices, result)))
                    self.events.put(('progress', sequence))
        except Exception as exc:
            reason = str(exc)
            if active:
                self.events.put(('live_fail', (active, reason)))
        finally:
            self.events.put(('live_done', reason))

    def set_reference(self, reference, evidence):
        self.reference = reference
        self.reference_evidence = evidence
        self.reference_label.set(f'已载入 {len(reference)} 个实际台号\n{evidence}')
        for row in self.results:
            apply_reference(row, self.reference, self.reference_evidence)
        self.refresh()
        self.status.set('已按独立清单重新核对，未覆盖的二维码保持待核实')
        try:
            save_reference_state(self.settings_path, reference, evidence)
        except OSError as exc:
            messagebox.showwarning('对照已载入，但无法记住设置', str(exc))

    def import_original_folder(self):
        folder = filedialog.askdirectory(title='选择后台导出的原始码文件夹（文件名即台号，例如 A01.jpg）')
        if not folder:
            return
        try:
            reference = load_reference_folder(folder)
        except (OSError, ValueError) as exc:
            messagebox.showerror('后台原始码导入失败', str(exc))
            return
        self.set_reference(reference, f'后台原始码文件名：{Path(folder).name}')
        self.status.set(f'已导入并记住 {len(reference)} 个后台台号，可以添加排版图开始核对')

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
    import sys
    if len(sys.argv) == 3 and sys.argv[1] == '--check-runtime':
        import json
        from wechat_reader import check_runtime
        try:
            result = check_runtime()
            code = 0
        except Exception as exc:
            result = {'error': str(exc)}
            code = 1
        Path(sys.argv[2]).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
        sys.exit(code)
    App().mainloop()

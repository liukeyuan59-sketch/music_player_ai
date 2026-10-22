"""随听: a private, portable Windows music player."""
import os
os.environ['PYGAME_HIDE_SUPPORT_PROMPT'] = '1'
import sys
from pathlib import Path

BASE = Path(sys.executable).parent if getattr(sys, 'frozen', False) else Path(__file__).parent
sys.path.insert(0, str(BASE / 'work' / 'deps'))
import json
import queue
import threading
import time
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, simpledialog
import pygame
from library import Library, smart_queue

BG = '#10151d'
PANEL = '#19212c'
FG = '#e7edf5'
MUTED = '#9aaabd'
ACCENT = '#71dcc5'


def clock(seconds):
    seconds = max(0, int(seconds))
    return f'{seconds // 60}:{seconds % 60:02d}'


class Player:
    def __init__(self, root, db_path=None):
        self.root = root
        self.lib = Library(db_path or BASE / 'data' / 'library.sqlite3')
        self.rows, self.by_id = [], {}
        self.visible, self.playlist = [], []
        self.cursor = -1
        self.current = None
        self.paused = False
        self.started = False
        self.offset = 0
        self.heard = 0.0
        self.recorded = False
        self.last_tick = time.monotonic()
        self.seeking = False
        self.scanning = False
        self.events = queue.Queue()
        self.filter_mode = '全部音乐'
        self.rules = self.lib.setting('rules', dict(days=3, gap=2, boost=True))
        self.audio_ready = True
        try:
            pygame.mixer.init()
        except pygame.error:
            self.audio_ready = False
        self.build()
        self.refresh()
        self.root.protocol('WM_DELETE_WINDOW', self.close)
        self.root.after(250, self.tick)
        self.root.after(1800, self.initial_scan)
        self.root.after(120000, self.auto_scan)
        self.root.bind('<Control-f>', lambda e: self.search_entry.focus_set())

    def button(self, parent, text, command, accent=False):
        return tk.Button(parent, text=text, command=command, bg=ACCENT if accent else '#263343',
                         fg=BG if accent else FG, activebackground='#91e9d5', activeforeground=BG,
                         relief='flat', bd=0, padx=15, pady=9, cursor='hand2', font=('Microsoft YaHei UI', 10))

    def label(self, parent, text, size=10, color=FG, **kw):
        return tk.Label(parent, text=text, bg=parent.cget('bg'), fg=color,
                        font=('Microsoft YaHei UI', size), **kw)

    def build(self):
        root = self.root
        root.title('随听 · 我的音乐，我的规则')
        root.geometry('1230x800')
        root.minsize(1000, 680)
        root.configure(bg=BG)
        style = ttk.Style()
        style.theme_use('clam')
        style.configure('Treeview', background=PANEL, fieldbackground=PANEL, foreground=FG,
                        rowheight=37, borderwidth=0, font=('Microsoft YaHei UI', 10))
        style.configure('Treeview.Heading', background='#233041', foreground=MUTED,
                        relief='flat', font=('Microsoft YaHei UI', 10))
        style.map('Treeview', background=[('selected', '#2c514e')], foreground=[('selected', '#ffffff')])
        style.configure('TCombobox', fieldbackground='#263343', background='#263343', foreground=FG)
        style.configure('Horizontal.TScale', background=PANEL, troughcolor='#344155')
        self.status = tk.StringVar(value='添加一个音乐文件夹，开始你的音乐库。')
        self.search = tk.StringVar()
        self.tag_filter = tk.StringVar(value='全部标签')
        self.folder_filter = tk.StringVar(value='全部文件夹')
        self.mode = tk.StringVar(value='智能随机')
        sidebar = tk.Frame(root, bg=PANEL, width=185)
        sidebar.pack(side='left', fill='y')
        sidebar.pack_propagate(False)
        self.label(sidebar, '随 听', 26, ACCENT).pack(anchor='w', padx=23, pady=(28, 3))
        self.label(sidebar, '让收藏，重新被听见', 9, MUTED).pack(anchor='w', padx=23, pady=(0, 35))
        self.nav_buttons = {}
        for name in ['全部音乐', '我的收藏', '最近加入', '还没听过', '文件失效', '播放队列']:
            b = self.button(sidebar, name, lambda n=name: self.navigate(n))
            b.pack(fill='x', padx=14, pady=4)
            self.nav_buttons[name] = b
        self.button(sidebar, '＋ 添加音乐文件夹', self.add_folder, True).pack(side='bottom', fill='x', padx=14, pady=20)
        self.label(sidebar, '本地存储 · 自由分类', 9, MUTED).pack(side='bottom', pady=5)
        self.body = tk.Frame(root, bg=BG)
        self.body.pack(side='left', fill='both', expand=True, padx=24, pady=20)
        header = tk.Frame(self.body, bg=BG)
        header.pack(fill='x')
        self.heading = self.label(header, '全部音乐', 25)
        self.heading.pack(side='left')
        self.button(header, '重新扫描', self.scan).pack(side='right', padx=(8, 0))
        self.button(header, '播放规则', self.rule_dialog).pack(side='right')
        self.stats = self.label(self.body, '', 10, MUTED)
        self.stats.pack(anchor='w', pady=(6, 19))
        filters = tk.Frame(self.body, bg=BG)
        filters.pack(fill='x', pady=(0, 12))
        self.search_entry = tk.Entry(filters, textvariable=self.search, bg=PANEL, fg=FG,
                                     insertbackground=FG, relief='flat', font=('Microsoft YaHei UI', 11))
        self.search_entry.pack(side='left', fill='x', expand=True, ipady=9, padx=(0, 10))
        self.search_entry.insert(0, '')
        self.tag_box = ttk.Combobox(filters, textvariable=self.tag_filter, state='readonly', width=13)
        self.tag_box.pack(side='left', padx=(0, 8), ipady=6)
        self.folder_box = ttk.Combobox(filters, textvariable=self.folder_filter, state='readonly', width=22)
        self.folder_box.pack(side='left', ipady=6)
        self.search.trace_add('write', lambda *a: self.schedule_filter())
        self.tag_box.bind('<<ComboboxSelected>>', lambda e: self.render())
        self.folder_box.bind('<<ComboboxSelected>>', lambda e: self.render())
        self.label(self.body, '搜索歌名、歌手、专辑、标签或路径 · 双击歌曲播放 · Ctrl / Shift 多选', 9, MUTED).pack(anchor='w', pady=(0, 12))
        actions = tk.Frame(self.body, bg=BG)
        actions.pack(fill='x', pady=(0, 12))
        for text, fn, accent in [('▶ 播放当前筛选', self.play_filtered, True), ('＋ 添加标签', self.add_tags, False),
                                 ('移除标签', lambda: self.add_tags(True), False), ('收藏 / 取消', self.favorite, False)]:
            self.button(actions, text, fn, accent).pack(side='left', padx=(0, 8))
        table = tk.Frame(self.body, bg=PANEL)
        table.pack(fill='both', expand=True)
        cols = ('favorite', 'title', 'artist', 'album', 'tags', 'duration')
        self.tree = ttk.Treeview(table, columns=cols, show='headings', selectmode='extended')
        for col, text, width in zip(cols, ['喜欢', '歌曲', '歌手', '专辑 / 文件夹', '我的标签', '时长'], [48, 230, 140, 170, 170, 65]):
            self.tree.heading(col, text=text)
            self.tree.column(col, width=width, minwidth=40, stretch=col not in ('favorite', 'duration'))
        self.tree.tag_configure('missing', foreground='#c39292')
        scroll = ttk.Scrollbar(table, orient='vertical', command=self.tree.yview)
        self.tree.configure(yscrollcommand=scroll.set)
        scroll.pack(side='right', fill='y')
        self.tree.pack(fill='both', expand=True)
        self.empty = self.label(table, '把你的音乐，带到这里\n\n点击左下角“添加音乐文件夹”\n歌曲继续保存在原来的位置', 14, MUTED, justify='center')
        self.tree.bind('<Double-1>', lambda e: self.play_selected())
        self.tree.bind('<Return>', lambda e: self.play_selected())
        self.tree.bind('<<TreeviewSelect>>', self.selection_info)
        self.detail = self.label(self.body, '尚未选择歌曲', 9, MUTED, anchor='w')
        self.detail.pack(fill='x', pady=(8, 5))
        self.label(self.body, '', 9).pack()
        tk.Label(self.body, textvariable=self.status, bg=BG, fg=ACCENT, anchor='w',
                 font=('Microsoft YaHei UI', 9), wraplength=850).pack(fill='x', pady=(0, 10))
        bottom = tk.Frame(self.body, bg=PANEL, padx=18, pady=14)
        bottom.pack(fill='x')
        self.now = self.label(bottom, '还没有播放音乐', 12)
        self.now.pack(anchor='w')
        self.timeline = tk.DoubleVar(value=0)
        self.seek = ttk.Scale(bottom, from_=0, to=100, variable=self.timeline)
        self.seek.pack(fill='x', pady=(8, 3))
        self.seek.bind('<ButtonPress-1>', lambda e: setattr(self, 'seeking', True))
        self.seek.bind('<ButtonRelease-1>', self.seek_to)
        controls = tk.Frame(bottom, bg=PANEL)
        controls.pack(fill='x')
        self.time_label = self.label(controls, '0:00 / 0:00', 10, MUTED, width=15)
        self.time_label.pack(side='left')
        self.button(controls, '上一首', self.previous).pack(side='left', padx=4)
        self.play_button = self.button(controls, '播放', self.toggle, True)
        self.play_button.pack(side='left', padx=4)
        self.button(controls, '下一首', self.next).pack(side='left', padx=4)
        mode = ttk.Combobox(controls, textvariable=self.mode, state='readonly',
                            values=['智能随机', '顺序播放', '单曲循环'], width=10)
        mode.pack(side='left', padx=12)
        self.volume = tk.DoubleVar(value=self.lib.setting('volume', 0.65))
        ttk.Scale(controls, from_=0, to=1, variable=self.volume, command=self.set_volume, length=100).pack(side='right')
        self.label(controls, '音量', 9, MUTED).pack(side='right', padx=5)
        self.set_volume()

    def schedule_filter(self):
        if hasattr(self, 'filter_job'):
            self.root.after_cancel(self.filter_job)
        self.filter_job = self.root.after(180, self.render)

    def refresh(self):
        self.rows = self.lib.tracks()
        self.by_id = {r['id']: r for r in self.rows}
        tags = sorted({t for r in self.rows for t in r['tags']})
        self.tag_box['values'] = ['全部标签'] + tags
        if self.tag_filter.get() not in self.tag_box['values']:
            self.tag_filter.set('全部标签')
        self.folder_box['values'] = ['全部文件夹'] + sorted({str(Path(r['path']).parent) for r in self.rows})
        if self.folder_filter.get() not in self.folder_box['values']:
            self.folder_filter.set('全部文件夹')
        self.render()

    def navigate(self, name):
        self.filter_mode = name
        self.render()

    def render(self):
        selected = set(self.tree.selection())
        text = self.search.get().strip().casefold()
        rows = self.rows
        name = self.filter_mode
        if name == '我的收藏': rows = [r for r in rows if r['favorite']]
        elif name == '最近加入': rows = [r for r in rows if time.time() - r['added'] < 7 * 86400]
        elif name == '还没听过': rows = [r for r in rows if not r['plays']]
        elif name == '文件失效': rows = [r for r in rows if r['missing']]
        elif name == '播放队列': rows = [self.by_id[i] for i in self.playlist[max(0, self.cursor):] if i in self.by_id]
        if name != '文件失效': rows = [r for r in rows if not r['missing']]
        if text:
            rows = [r for r in rows if text in ' '.join([r['title'], r['artist'], r['album'], r['path']] + r['tags']).casefold()]
        if self.tag_filter.get() != '全部标签': rows = [r for r in rows if self.tag_filter.get() in r['tags']]
        if self.folder_filter.get() != '全部文件夹': rows = [r for r in rows if str(Path(r['path']).parent) == self.folder_filter.get()]
        self.visible = [r['id'] for r in rows]
        self.tree.delete(*self.tree.get_children())
        if not rows:
            self.empty.configure(text=('把你的音乐，带到这里\n\n点击左下角“添加音乐文件夹”\n歌曲继续保存在原来的位置' if not self.rows
                                       else '这里还没有歌曲\n\n试试其他分类、标签或搜索词'))
            self.empty.place(relx=0.5, rely=0.5, anchor='center')
        else:
            self.empty.place_forget()
        for r in rows:
            self.tree.insert('', 'end', iid=str(r['id']), values=(
                '♥' if r['favorite'] else '', r['title'], r['artist'], r['album'],
                ' · '.join(r['tags']), clock(r['duration']) if r['duration'] else '—'),
                tags=('missing',) if r['missing'] else ())
        self.tree.selection_set([i for i in selected if i in set(map(str, self.visible))])
        self.heading.configure(text=name)
        self.stats.configure(text=f'{len(rows):,} 首歌曲   /   音乐库共 {len(self.rows):,} 首   /   {len(self.lib.roots())} 个来源文件夹')
        for key, button in self.nav_buttons.items():
            button.configure(bg='#2c514e' if key == name else '#263343')

    def selected(self):
        return [int(i) for i in self.tree.selection()]

    def selection_info(self, event=None):
        ids = self.selected()
        text = self.by_id[ids[0]]['path'] if len(ids) == 1 else f'已选择 {len(ids)} 首歌曲'
        self.detail.configure(text=text)

    def add_folder(self):
        if self.scanning: return
        path = filedialog.askdirectory(title='选择音乐文件夹（保留原目录）', parent=self.root)
        if path:
            self.lib.add_root(path)
            self.scan()

    def initial_scan(self):
        if self.lib.roots(): self.scan()

    def auto_scan(self):
        if self.lib.roots() and not self.scanning:
            self.scan()
        self.root.after(120000, self.auto_scan)

    def scan(self):
        if self.scanning: return
        if not self.lib.roots():
            self.add_folder()
            return
        self.scanning = True
        self.status.set('正在扫描音乐文件夹… 可以继续播放已有歌曲。')
        def worker():
            try:
                result = self.lib.scan(lambda m: self.events.put(('progress', m)))
                self.events.put(('scanned', result))
            except Exception as error:
                self.events.put(('error', str(error)))
        threading.Thread(target=worker, daemon=True).start()

    def add_tags(self, remove=False):
        ids = self.selected()
        if not ids:
            self.status.set('先选择歌曲；按 Ctrl 或 Shift 可以多选。')
            return
        value = simpledialog.askstring('移除标签' if remove else '添加标签',
                    f'为选中的 {len(ids)} 首歌' + ('移除' if remove else '添加') + '标签，用逗号分隔：', parent=self.root)
        if value:
            tags = list(dict.fromkeys(t.strip() for t in value.replace('，', ',').split(',') if t.strip()))
            self.lib.edit_tags(ids, tags, remove)
            self.refresh()
            self.status.set(f'已更新 {len(ids)} 首歌曲的标签。')

    def favorite(self):
        ids = self.selected()
        if not ids:
            self.status.set('请先选择要收藏的歌曲。')
            return
        value = 0 if all(self.by_id[i]['favorite'] for i in ids) else 1
        self.lib.update(ids, 'favorite', value)
        self.refresh()

    def make_queue(self):
        tracks = [self.by_id[i] for i in self.visible if not self.by_id[i]['missing']]
        if self.mode.get() == '智能随机':
            return smart_queue(tracks, self.rules['days'], self.rules['gap'], self.rules['boost'])
        return [r['id'] for r in tracks]

    def play_filtered(self):
        self.playlist = self.make_queue()
        self.cursor = -1
        self.next()

    def play_selected(self):
        ids = self.selected()
        if not ids: return
        self.playlist = self.make_queue()
        if ids[0] not in self.playlist:
            self.status.set('这首歌的文件无法访问，请重新扫描或连接原磁盘。')
            return
        self.playlist.remove(ids[0])
        self.playlist.insert(0, ids[0])
        self.cursor = 0
        self.start(ids[0])

    def start(self, track_id):
        if not self.audio_ready:
            self.status.set('无法初始化音频设备，请检查输出设备后重新启动随听。')
            return False
        track = self.by_id[track_id]
        try:
            pygame.mixer.music.load(track['path'])
            pygame.mixer.music.play()
        except (pygame.error, OSError) as error:
            self.started = False
            self.status.set('无法播放：' + track['title'] + '。文件可能失效或格式不支持。' + str(error))
            self.play_button.configure(text='播放')
            return False
        self.current, self.paused, self.started = track, False, True
        self.offset, self.heard, self.recorded = 0, 0.0, False
        self.last_tick = time.monotonic()
        self.timeline.set(0)
        self.seek.configure(to=max(track['duration'], 1))
        self.now.configure(text=track['title'] + '   /   ' + track['artist'])
        self.play_button.configure(text='暂停')
        self.status.set(f'队列 {self.cursor + 1} / {len(self.playlist)} · 听满 30 秒（短曲为一半）记入播放历史。')
        return True

    def toggle(self):
        if not self.started:
            self.play_filtered()
        elif self.paused:
            pygame.mixer.music.unpause()
            self.paused = False
            self.last_tick = time.monotonic()
            self.play_button.configure(text='暂停')
        else:
            pygame.mixer.music.pause()
            self.paused = True
            self.play_button.configure(text='继续')

    def next(self, ended=False):
        if ended and self.mode.get() == '单曲循环' and self.current:
            self.start(self.current['id'])
            return
        while self.cursor + 1 < len(self.playlist):
            self.cursor += 1
            if self.start(self.playlist[self.cursor]):
                if self.filter_mode == '播放队列': self.render()
                return
        if self.audio_ready: pygame.mixer.music.stop()
        self.started = False
        self.play_button.configure(text='播放')
        self.status.set('本轮队列已结束。点击“播放当前筛选”开始新一轮。' if self.playlist else '还没有可播放的歌曲，请先添加音乐文件夹。')

    def previous(self):
        if self.cursor > 0:
            self.cursor -= 1
            self.start(self.playlist[self.cursor])

    def seek_to(self, event=None):
        self.seeking = False
        if not self.started or not self.current: return
        if not self.current['duration'] or Path(self.current['path']).suffix.lower() == '.wav':
            self.status.set('此文件暂不支持拖动进度。')
            return
        position = self.timeline.get()
        try:
            pygame.mixer.music.play(start=position)
            self.offset = position
            if self.paused: pygame.mixer.music.pause()
        except pygame.error:
            self.status.set('此音频编码不支持拖动进度，可以继续正常播放。')

    def set_volume(self, value=None):
        if self.audio_ready: pygame.mixer.music.set_volume(self.volume.get())

    def tick(self):
        try:
            while True:
                kind, value = self.events.get_nowait()
                if kind == 'progress': self.status.set(value)
                elif kind == 'scanned':
                    self.scanning = False
                    self.refresh()
                    count, errors = value
                    self.status.set(f'扫描完成：{count} 首。' + (f'有 {len(errors)} 项读取问题，详情见 data/scan-errors.txt。' if errors else ''))
                    (self.lib.path.parent / 'scan-errors.txt').write_text('\n'.join(errors), encoding='utf-8')
                elif kind == 'error':
                    self.scanning = False
                    self.status.set('扫描失败：' + value)
        except queue.Empty:
            pass
        now = time.monotonic()
        elapsed = min(now - self.last_tick, 1)
        self.last_tick = now
        if self.started and not self.paused:
            if pygame.mixer.music.get_busy():
                self.heard += elapsed
                position = max(0, pygame.mixer.music.get_pos() / 1000) + self.offset
                if not self.seeking: self.timeline.set(position)
                self.time_label.configure(text=clock(position) + ' / ' + clock(self.current['duration']))
                threshold = min(30, self.current['duration'] / 2) if self.current['duration'] else 30
                if not self.recorded and self.heard >= threshold:
                    self.lib.record_play(self.current['id'])
                    self.recorded = True
                    self.refresh()
            else:
                self.next(ended=True)
        self.root.after(250, self.tick)

    def rule_dialog(self):
        dialog = tk.Toplevel(self.root)
        dialog.title('我的播放规则')
        dialog.configure(bg=PANEL)
        dialog.geometry('450x340')
        dialog.transient(self.root)
        dialog.grab_set()
        self.label(dialog, '让随机更合你的心意', 17, ACCENT).pack(pady=22)
        days, gap = tk.IntVar(value=self.rules['days']), tk.IntVar(value=self.rules['gap'])
        boost = tk.BooleanVar(value=self.rules['boost'])
        for title, var, maximum in [('最近多少天听过的少放', days, 365), ('同一歌手尽量间隔几首', gap, 10)]:
            row = tk.Frame(dialog, bg=PANEL)
            row.pack(fill='x', padx=28, pady=8)
            self.label(row, title).pack(side='left')
            tk.Spinbox(row, from_=0, to=maximum, textvariable=var, width=5).pack(side='right')
        tk.Checkbutton(dialog, text='让收藏歌曲更容易排在前面', variable=boost, bg=PANEL, fg=FG,
                       selectcolor=BG, activebackground=PANEL, activeforeground=FG).pack(pady=10)
        self.label(dialog, '每轮不重复；歌手较少时，间隔可能无法满足。\n规则对下一次生成的智能随机队列生效。', 9, MUTED).pack()
        def save():
            try:
                d, g = days.get(), gap.get()
                if not 0 <= d <= 365 or not 0 <= g <= 10: raise ValueError()
            except (ValueError, tk.TclError):
                messagebox.showerror('数值不正确', '天数为 0–365，歌手间隔为 0–10。', parent=dialog)
                return
            self.rules = dict(days=d, gap=g, boost=boost.get())
            self.lib.save_setting('rules', self.rules)
            dialog.destroy()
            self.status.set('规则已保存，下次点击“播放当前筛选”时生效。')
        self.button(dialog, '保存规则', save, True).pack(pady=15)

    def close(self):
        if self.scanning:
            messagebox.showinfo('扫描进行中', '请等本次扫描完成后再关闭。', parent=self.root)
            return
        self.lib.save_setting('volume', self.volume.get())
        if self.audio_ready:
            pygame.mixer.music.stop()
            pygame.mixer.music.unload()
            pygame.mixer.quit()
        self.root.destroy()


if __name__ == '__main__':
    if '--self-test' in sys.argv:
        os.environ['SDL_AUDIODRIVER'] = 'dummy'
        from selftest import run
        run(BASE / 'self-test.json')
    else:
        root = tk.Tk()
        Player(root)
        root.mainloop()

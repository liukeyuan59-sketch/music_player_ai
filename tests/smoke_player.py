"""Exercise a real desktop window using generated silence; no user music required."""
import os
os.environ['SDL_AUDIODRIVER'] = 'dummy'
import sys
from pathlib import Path
import tempfile
import time
import tkinter as tk

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from player import Player
from test_library import wav

with tempfile.TemporaryDirectory() as directory:
    base = Path(directory)
    wav(base / 'music' / '测试歌手 - 测试音频.wav', 3)
    root = tk.Tk()
    app = Player(root, base / 'data' / 'library.sqlite3')
    app.lib.add_root(base / 'music')
    app.lib.scan()
    app.refresh()
    root.update()
    assert len(app.visible) == 1
    assert app.tree.winfo_height() > 100
    app.tree.selection_set(str(app.visible[0]))
    app.play_selected()
    assert app.started and app.current['title'] == '测试音频'
    app.toggle()
    assert app.paused
    app.toggle()
    assert not app.paused
    deadline = time.monotonic() + 2.2
    while time.monotonic() < deadline:
        root.update()
        time.sleep(0.02)
    assert app.lib.tracks()[0]['plays'] == 1
    app.search.set('不存在的歌')
    root.update()
    app.render()
    assert not app.visible
    app.search.set('')
    app.render()
    app.rule_dialog()
    root.update()
    for widget in root.winfo_children():
        if isinstance(widget, tk.Toplevel): widget.destroy()
    app.close()
    print('PASS: desktop layout, search, playback, pause/resume, history and rules dialog')

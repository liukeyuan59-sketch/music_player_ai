"""Packaged-runtime smoke test, invoked explicitly with --self-test."""
import json
from pathlib import Path
import tempfile
import time
import traceback
import wave
import tkinter as tk


def run(report_path):
    from player import Player
    root = None
    app = None
    result = {'passed': False}
    with tempfile.TemporaryDirectory() as directory:
        try:
            base = Path(directory)
            music = base / 'music'
            music.mkdir()
            song = music / '测试歌手 - 测试音频.wav'
            with wave.open(str(song), 'wb') as audio:
                audio.setparams((1, 2, 8000, 0, 'NONE', 'not compressed'))
                audio.writeframes(b'\0\0' * 24000)
            root = tk.Tk()
            root.withdraw()
            app = Player(root, base / 'data' / 'library.sqlite3')
            app.lib.add_root(music)
            app.lib.scan()
            app.refresh()
            assert len(app.visible) == 1, 'Scan did not find generated audio'
            assert app.rows[0]['duration'] == 3, 'Bundled metadata reader failed'
            app.tree.selection_set(str(app.visible[0]))
            app.play_selected()
            assert app.started, 'Bundled audio player failed'
            app.toggle()
            assert app.paused
            app.toggle()
            assert not app.paused
            deadline = time.monotonic() + 2.2
            while time.monotonic() < deadline:
                root.update()
                time.sleep(0.02)
            assert app.lib.tracks()[0]['plays'] == 1, 'Listening history was not recorded'
            app.favorite()
            assert app.lib.tracks()[0]['favorite'] == 1
            result = {'passed': True, 'checks': ['window', 'SQLite', 'metadata', 'audio decode', 'pause/resume', 'history', 'favorite']}
        except Exception:
            result['error'] = traceback.format_exc()
        finally:
            if app:
                app.scanning = False
                app.close()
            elif root:
                root.destroy()
    Path(report_path).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')

"""Local library and weighted, non-repeating queue. Never writes audio files."""
import json
import math
import os
from pathlib import Path
import random
import sqlite3
import time
from contextlib import contextmanager

EXTENSIONS = {'.mp3', '.flac', '.ogg', '.wav', '.opus', '.m4a', '.aac', '.wma'}


def identity(path):
    return os.path.normcase(os.path.abspath(path))


def metadata(path):
    stem = path.stem
    artist, title = stem.split(' - ', 1) if ' - ' in stem else ('未知歌手', stem)
    result = dict(title=title, artist=artist, album=path.parent.name, duration=0.0)
    try:
        from mutagen import File
        audio = File(path, easy=True)
        if audio is not None:
            for key in ('title', 'artist', 'album'):
                if audio.get(key):
                    result[key] = ' / '.join(audio[key])
            result['duration'] = float(audio.info.length)
    except Exception:
        pass
    return result


class Library:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.execute('PRAGMA journal_mode=WAL')
            db.executescript('''
                CREATE TABLE IF NOT EXISTS tracks (
                    id INTEGER PRIMARY KEY, path TEXT UNIQUE NOT NULL,
                    title TEXT, artist TEXT, album TEXT, duration REAL DEFAULT 0,
                    mtime REAL, size INTEGER, favorite INTEGER DEFAULT 0,
                    tags TEXT DEFAULT '[]', added REAL, last_played REAL DEFAULT 0,
                    plays INTEGER DEFAULT 0, missing INTEGER DEFAULT 0);
                CREATE TABLE IF NOT EXISTS roots (path TEXT PRIMARY KEY);
                CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT);
            ''')

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=20)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def roots(self):
        with self.connect() as db:
            return [r[0] for r in db.execute('SELECT path FROM roots ORDER BY path')]

    def add_root(self, path):
        path = identity(path)
        if not Path(path).is_dir():
            raise ValueError('文件夹不存在或无法访问')
        with self.connect() as db:
            db.execute('INSERT OR IGNORE INTO roots VALUES (?)', (path,))

    def scan(self, progress=lambda message: None):
        count, errors = 0, []
        with self.connect() as db:
            for root in self.roots():
                if not Path(root).is_dir():
                    errors.append('无法访问：' + root)
                    continue
                def walk_error(error):
                    errors.append(str(error))
                for folder, dirs, files in os.walk(root, onerror=walk_error, followlinks=False):
                    dirs[:] = [d for d in dirs if not Path(folder, d).is_symlink()]
                    for name in files:
                        path = Path(folder, name)
                        if path.suffix.lower() not in EXTENSIONS:
                            continue
                        try:
                            stat = path.stat()
                            key = identity(path)
                            old = db.execute('SELECT mtime,size FROM tracks WHERE path=?', (key,)).fetchone()
                            if not old or old['mtime'] != stat.st_mtime or old['size'] != stat.st_size:
                                info = metadata(path)
                                db.execute('''INSERT INTO tracks
                                    (path,title,artist,album,duration,mtime,size,added)
                                    VALUES (?,?,?,?,?,?,?,?) ON CONFLICT(path) DO UPDATE SET
                                    title=excluded.title,artist=excluded.artist,album=excluded.album,
                                    duration=excluded.duration,mtime=excluded.mtime,size=excluded.size,missing=0''',
                                    (key, info['title'], info['artist'], info['album'], info['duration'],
                                     stat.st_mtime, stat.st_size, time.time()))
                            else:
                                db.execute('UPDATE tracks SET missing=0 WHERE path=?', (key,))
                            count += 1
                            if count % 20 == 0:
                                db.commit()
                                progress(f'已扫描 {count} 首 · {name}')
                        except OSError as error:
                            errors.append(str(error))
                db.commit()
            # Missing entries retain all personal data and can recover on the next scan.
            for row in db.execute('SELECT id,path FROM tracks').fetchall():
                db.execute('UPDATE tracks SET missing=? WHERE id=?',
                           (int(not Path(row['path']).is_file()), row['id']))
        return count, errors

    def tracks(self):
        with self.connect() as db:
            result = [dict(row) for row in db.execute('SELECT * FROM tracks ORDER BY title COLLATE NOCASE')]
        for row in result:
            row['tags'] = json.loads(row['tags'])
        return result

    def update(self, ids, field, value):
        if field not in {'favorite', 'tags'}:
            raise ValueError('Invalid field')
        if field == 'tags':
            value = json.dumps(value, ensure_ascii=False)
        with self.connect() as db:
            db.executemany(f'UPDATE tracks SET {field}=? WHERE id=?', [(value, i) for i in ids])

    def edit_tags(self, ids, tags, remove=False):
        with self.connect() as db:
            for track_id in ids:
                row = db.execute('SELECT tags FROM tracks WHERE id=?', (track_id,)).fetchone()
                if row:
                    existing = json.loads(row['tags'])
                    updated = [t for t in existing if t not in tags] if remove else list(dict.fromkeys(existing + tags))
                    db.execute('UPDATE tracks SET tags=? WHERE id=?', (json.dumps(updated, ensure_ascii=False), track_id))

    def record_play(self, track_id):
        with self.connect() as db:
            db.execute('UPDATE tracks SET plays=plays+1,last_played=? WHERE id=?', (time.time(), track_id))

    def setting(self, key, default=None):
        with self.connect() as db:
            row = db.execute('SELECT value FROM settings WHERE key=?', (key,)).fetchone()
        return json.loads(row[0]) if row else default

    def save_setting(self, key, value):
        with self.connect() as db:
            db.execute('INSERT OR REPLACE INTO settings VALUES (?,?)', (key, json.dumps(value)))


def smart_queue(tracks, recent_days=3, artist_gap=2, favorite_boost=True, rng=None, now=None):
    """Weighted shuffle without replacement; artist spacing is best-effort."""
    rng = rng or random.Random()
    now = time.time() if now is None else now
    ranked = []
    for track in tracks:
        if track['missing']:
            continue
        weight = 2.0 if favorite_boost and track['favorite'] else 1.0
        if track['last_played'] and now - track['last_played'] < recent_days * 86400:
            weight *= 0.18
        ranked.append((-math.log(max(rng.random(), 1e-12)) / weight, track))
    pending = [t for _, t in sorted(ranked, key=lambda pair: pair[0])]
    result = []
    while pending:
        recent = {t['artist'] for t in result[-artist_gap:]} if artist_gap else set()
        # Unknown artists do not imply the same performer.
        recent.discard('未知歌手')
        pick = next((i for i, t in enumerate(pending) if t['artist'] not in recent), 0)
        result.append(pending.pop(pick))
    return [t['id'] for t in result]

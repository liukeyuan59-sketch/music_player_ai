import hashlib
from pathlib import Path
import random
import sys
import tempfile
import time
import unittest
import wave

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'work' / 'deps'))
from library import Library, smart_queue


def wav(path, seconds=1):
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), 'wb') as out:
        out.setparams((1, 2, 8000, 0, 'NONE', 'not compressed'))
        out.writeframes(b'\0\0' * int(8000 * seconds))


class LibraryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.music = self.base / '音乐库'
        self.song = self.music / '歌手甲 - 夜晚.wav'
        wav(self.song)
        self.lib = Library(self.base / 'data' / 'library.sqlite3')
        self.lib.add_root(self.music)

    def test_scan_keeps_personal_data_and_source_bytes(self):
        before = hashlib.sha256(self.song.read_bytes()).hexdigest()
        self.assertEqual(self.lib.scan()[0], 1)
        row = self.lib.tracks()[0]
        self.assertEqual(row['artist'], '歌手甲')
        self.assertAlmostEqual(row['duration'], 1, delta=0.01)
        self.lib.edit_tags([row['id']], ['夜晚', '放松'])
        self.lib.edit_tags([row['id']], ['放松', '开车'])
        self.lib.edit_tags([row['id']], ['开车'], remove=True)
        self.lib.update([row['id']], 'favorite', 1)
        self.lib.record_play(row['id'])
        # Changed source content must refresh metadata without erasing annotations.
        wav(self.song, 2)
        changed = hashlib.sha256(self.song.read_bytes()).hexdigest()
        self.lib.scan()
        row = self.lib.tracks()[0]
        self.assertEqual(row['tags'], ['夜晚', '放松'])
        self.assertEqual((row['favorite'], row['plays']), (1, 1))
        self.assertEqual(hashlib.sha256(self.song.read_bytes()).hexdigest(), changed)
        self.assertNotEqual(before, changed)

    def test_overlapping_roots_no_duplicates_missing_recovers(self):
        nested = self.music / '专辑' / '歌手乙 - 清晨.wav'
        wav(nested)
        self.lib.add_root(nested.parent)
        self.lib.scan()
        self.assertEqual(len(self.lib.tracks()), 2)
        content = nested.read_bytes()
        nested.unlink()
        self.lib.scan()
        self.assertEqual(sum(r['missing'] for r in self.lib.tracks()), 1)
        nested.write_bytes(content)
        self.lib.scan()
        self.assertFalse(any(r['missing'] for r in self.lib.tracks()))

    def test_settings_survive_restart(self):
        self.lib.save_setting('rules', {'days': 7, 'gap': 3, 'boost': False})
        reopened = Library(self.lib.path)
        self.assertEqual(reopened.setting('rules')['gap'], 3)


class QueueTests(unittest.TestCase):
    def tracks(self, count=30):
        return [dict(id=i, artist=f'歌手{i % 5}', missing=0, favorite=0, last_played=0) for i in range(count)]

    def test_unique_valid_and_spacing(self):
        tracks = self.tracks()
        tracks.append(dict(id=999, artist='失效', missing=1, favorite=1, last_played=0))
        result = smart_queue(tracks, artist_gap=2, rng=random.Random(4))
        self.assertEqual(len(result), 30)
        self.assertEqual(len(set(result)), 30)
        self.assertNotIn(999, result)
        # When at least three artists remain, the required spacing is feasible.
        pending = set(range(30))
        for index, item in enumerate(result):
            recent = {tracks[j]['artist'] for j in result[max(0, index - 2):index]}
            if any(tracks[j]['artist'] not in recent for j in pending):
                self.assertNotIn(tracks[item]['artist'], recent)
            pending.remove(item)

    def test_recent_tracks_are_less_likely_early(self):
        now = time.time()
        tracks = self.tracks(2)
        tracks[0]['last_played'] = now - 10
        recent_first = sum(smart_queue(tracks, rng=random.Random(seed), now=now)[0] == 0 for seed in range(1000))
        self.assertLess(recent_first, 230)
        self.assertGreater(recent_first, 80)

    def test_artist_shortage_and_empty(self):
        tracks = self.tracks(10)
        for row in tracks: row['artist'] = '同一歌手'
        self.assertEqual(len(smart_queue(tracks, artist_gap=10)), 10)
        self.assertEqual(smart_queue([]), [])

    def test_thousands_of_tracks(self):
        tracks = self.tracks(5000)
        start = time.monotonic()
        result = smart_queue(tracks, rng=random.Random(5))
        self.assertEqual(len(set(result)), 5000)
        self.assertLess(time.monotonic() - start, 5)


if __name__ == '__main__':
    unittest.main()

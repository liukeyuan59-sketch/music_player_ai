"""Build a portable Windows folder and include readable sources and notices."""
from pathlib import Path
import os
import shutil
import subprocess
import sys

base = Path(__file__).resolve().parent
env = os.environ.copy()
env['PYTHONPATH'] = str(base / 'work' / 'deps')
subprocess.run([
    sys.executable, '-m', 'PyInstaller', '--noconfirm', '--windowed', '--onedir',
    '--name', '随听', '--distpath', str(base / 'outputs'),
    '--workpath', str(base / 'work' / 'build'), '--specpath', str(base / 'work'),
    '--paths', str(base / 'work' / 'deps'),
    '--exclude-module', 'pkg_resources', '--exclude-module', 'numpy',
    '--exclude-module', 'PIL', str(base / 'player.py')
], cwd=base, env=env, check=True)
target = base / 'outputs' / '随听'
for filename in ['README.md', 'THIRD_PARTY_NOTICES.md', 'GPL-2.0.txt']:
    shutil.copy2(base / filename, target / filename)
shutil.copytree(base / 'licenses', target / 'licenses', dirs_exist_ok=True)
source = target / 'source'
source.mkdir(exist_ok=True)
for filename in ['player.py', 'library.py', 'selftest.py', 'build.py', 'requirements.txt', 'README.md', 'GPL-2.0.txt', 'THIRD_PARTY_NOTICES.md']:
    shutil.copy2(base / filename, source / filename)
shutil.copytree(base / 'licenses', source / 'licenses', dirs_exist_ok=True)
shutil.copytree(base / 'tests', source / 'tests', dirs_exist_ok=True, ignore=shutil.ignore_patterns('__pycache__'))
shutil.copytree(base / 'work' / 'deps' / 'mutagen', source / 'third_party' / 'mutagen',
                dirs_exist_ok=True, ignore=shutil.ignore_patterns('__pycache__'))
print('Built:', target)

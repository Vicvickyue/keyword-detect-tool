"""Exercise the independent frozen checker, including nested archives and failure reporting."""
import json
import os
import subprocess
import tempfile
import zipfile
import tarfile
import io
from pathlib import Path
import time


def main():
    exe = Path('dist/FileTypeCheckTool/FileTypeCheckTool.exe').resolve()
    env = dict(os.environ, PATH=str(Path(os.environ['WINDIR']) / 'System32'))
    for key in ('PYTHONHOME', 'PYTHONPATH', 'QT_PLUGIN_PATH', 'QT_QPA_PLATFORM_PLUGIN_PATH'):
        env.pop(key, None)
    with tempfile.TemporaryDirectory(prefix='typecheck-smoke-') as folder:
        root = Path(folder); source = root / 'input'; source.mkdir()
        (source / 'visible.GDS').write_bytes(b'not a real gds: suffix-only check')
        (source / 'excluded.gds.txt').touch()
        (source / 'unchecked.mdl').touch()
        nested = root / 'inner.zip'
        with zipfile.ZipFile(nested, 'w') as z: z.writestr('folder/chip.oas', b'')
        with zipfile.ZipFile(source / 'outer.zip', 'w') as z:
            z.write(nested, 'inner.zip'); z.writestr('light.src', b'')
        tar_path = source / 'no-end-markers.tar'
        with tarfile.open(tar_path, 'w') as tar:
            info = tarfile.TarInfo('chip.gds'); info.size = 3
            tar.addfile(info, io.BytesIO(b'abc'))
        tar_path.write_bytes(tar_path.read_bytes()[:1024])
        with tarfile.open(source / 'compressed.tgz', 'w:gz') as tar:
            tar.addfile(tarfile.TarInfo('chip.oas'))
        output = Path('output/typecheck-smoke').resolve()
        command = [str(exe), '--scan', str(source), '--output', str(output), '--types', '.gds', '.oas', '.src']
        assert subprocess.run(command, env=env, timeout=90).returncode == 0
        log = sorted(output.glob('*.jsonl'))[-1]
        records = [json.loads(line) for line in log.read_text(encoding='utf-8').splitlines()]
        assert records[0]['matched'] == 5 and records[0]['state'] == '完成'
        assert records[0]['counts'] == {'.gds': 2, '.oas': 2, '.src': 1}
        (source / 'broken.zip').write_bytes(b'broken')
        assert subprocess.run(command, env=env, timeout=90).returncode == 2
        latest = sorted(output.glob('*.jsonl'))[-1]
        data = json.loads(latest.read_text(encoding='utf-8').splitlines()[0])
        assert data['issues'] == 1 and data['matched'] == 5
    process = subprocess.Popen([str(exe)], env=dict(env, QT_QPA_PLATFORM='offscreen'))
    try:
        time.sleep(3)
        assert process.poll() is None, 'GUI exited unexpectedly'
    finally:
        if process.poll() is None: process.terminate()
        process.wait(timeout=10)
    print('Frozen CLI selection, nested archives, failure status and GUI startup passed.')


if __name__ == '__main__': main()

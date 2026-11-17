import csv
import gzip
import io
import json
import tarfile
import zipfile
from pathlib import Path
from threading import Event

import fitz
import pytest
from typecheck import TYPES
from typecheck.engine import Config, Scanner, execute


def scan(tmp_path, path, **kwargs):
    return Scanner(Config([path], tmp_path / 'output', **kwargs)).run()


def test_suffix_selection_case_and_false_suffix(tmp_path):
    source = tmp_path / 'input'; source.mkdir()
    for name in ['a.GDS', 'b.gdsii', 'c.gds.txt', 'd.src', 'none', 'folder.yaml.txt']:
        (source / name).write_bytes(b'not inspected')
    (source / 'directory.gds').mkdir()
    result = scan(tmp_path, source, selected={'.gds', '.gdsii'})
    assert result['matched'] == 2
    assert result['counts'] == {'.gds': 1, '.gdsii': 1}
    assert result['state'] == '完成'


def test_all_types_and_nested_folders(tmp_path):
    folder = tmp_path / 'input' / 'nested'; folder.mkdir(parents=True)
    for suffix in TYPES: (folder / ('sample' + suffix)).touch()
    result = scan(tmp_path, folder.parent)
    assert result['matched'] == len(TYPES) == 13


def test_duplicate_inputs_and_output_exclusion(tmp_path):
    source = tmp_path / 'input'; source.mkdir()
    file = source / 'a.gds'; file.touch()
    output = source / 'output'; output.mkdir(); (output / 'skip.gds').touch()
    result = Scanner(Config([source, file, source], output)).run()
    assert result['matched'] == 1


def test_names_only_no_extract_large_plain_member(tmp_path, monkeypatch):
    source = tmp_path / 'archive.zip'
    with zipfile.ZipFile(source, 'w') as z: z.writestr('nested/sample.gds', b'x' * 300)
    scanner = Scanner(Config([source], tmp_path / 'out', max_file_bytes=10))
    monkeypatch.setattr(scanner.reader, 'extract', lambda *args: pytest.fail('ordinary member extracted'))
    result = scanner.run()
    assert result['matched'] == 1 and result['state'] == '完成'
    assert 'nested' in result['rows'][1]['directory']


def test_five_nested_archives_and_depth_limit(tmp_path):
    payload = b'ignored'
    name = 'chip.gds'
    for i in range(5):
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, 'w') as z: z.writestr(name, payload)
        payload = buffer.getvalue(); name = f'level{i}.zip'
    source = tmp_path / name; source.write_bytes(payload)
    result = scan(tmp_path, source, max_depth=5)
    assert result['matched'] == 1 and result['state'] == '完成'
    with zipfile.ZipFile(tmp_path / 'outer.zip', 'w') as z: z.write(source, name)
    limited = scan(tmp_path, tmp_path / 'outer.zip', max_depth=5)
    assert limited['state'] != '完成' and limited['matched'] == 0


def test_tgz_and_disabled_archives(tmp_path):
    source = tmp_path / 'bundle.tgz'
    with tarfile.open(source, 'w:gz') as tar:
        info = tarfile.TarInfo('inner/a.oas'); info.size = 3
        tar.addfile(info, io.BytesIO(b'xxx'))
    assert scan(tmp_path, source)['matched'] == 1
    assert scan(tmp_path, source, archives=False)['matched'] == 0


def test_corrupt_archive_and_max_files(tmp_path):
    source = tmp_path / 'broken.zip'; source.write_bytes(b'broken')
    result = scan(tmp_path, source)
    assert result['issues'] == 1 and result['state'] != '完成'
    folder = tmp_path / 'input'; folder.mkdir()
    for i in range(3): (folder / f'{i}.gds').touch()
    result = scan(tmp_path, folder, max_files=1)
    assert result['matched'] == 1 and '受限' in result['state']


def test_cancelled_not_reported_as_complete(tmp_path):
    file = tmp_path / 'a.gds'; file.touch()
    cancel = Event(); cancel.set()
    result = Scanner(Config([file], tmp_path / 'out'), cancel).run()
    assert result['matched'] == 0 and '取消' in result['state']


def test_invalid_selection(tmp_path):
    with pytest.raises(ValueError): Config([tmp_path], tmp_path / 'out', selected=set()).validate()
    file = tmp_path / 'a.gds'; file.touch()
    with pytest.raises(ValueError): Config([file], tmp_path).validate()


def test_reports_complete_csv_and_sequence(tmp_path):
    source = tmp_path / 'input'; source.mkdir()
    (source / '=sample.GDS').touch(); (source / 'other.txt').touch()
    pdf, result = execute(Config([source], tmp_path / 'reports', selected={'.gds'}))
    with fitz.open(pdf) as doc:
        text = ''.join(page.get_text() for page in doc)
        assert '=sample.GDS' in text and 'other.txt' not in text
    with pdf.with_suffix('.csv').open(encoding='utf-8-sig', newline='') as f:
        rows = list(csv.reader(f))
    assert len(rows) == 3 and rows[1][1] == "'=sample.GDS"
    records = [json.loads(line) for line in pdf.with_suffix('.jsonl').read_text(encoding='utf-8').splitlines()]
    assert records[0]['matched'] == 1
    assert records[1]['name'] == '=sample.GDS'
    second, _ = execute(Config([source], tmp_path / 'reports', selected={'.gds'}, full_list=True))
    assert second != pdf and pdf.exists()
    with fitz.open(second) as doc: assert 'other.txt' in ''.join(p.get_text() for p in doc)


def test_gui_selection(tmp_path):
    from PySide6.QtWidgets import QApplication
    from typecheck.gui import Window
    app = QApplication.instance() or QApplication([])
    w = Window(); w.add_paths([str(tmp_path), str(tmp_path)])
    w.select_all(False); w.checks['.gds'].setChecked(True)
    assert w.sources.count() == 1 and w.config().selected == {'.gds'}
    w.select_all(True); assert len(w.config().selected) == 13
    w.close()

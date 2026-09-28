import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET

meta = json.loads((Path(__file__).parent / 'case.json').read_text())
work = Path(sys.argv[1]).resolve()
evidence = Path(sys.argv[2]).resolve()
evidence.mkdir(parents=True, exist_ok=True)
python = sys.executable
native = meta['repo'].endswith('/tnco')
source = work / meta['source']
fixed = source.read_bytes()
summary = {}

def run(label, command, expected=0, cwd=work, timeout=600):
    with (evidence / (label + '.log')).open('w') as log:
        result = subprocess.run(command, cwd=cwd, stdout=log,
                                stderr=subprocess.STDOUT, timeout=timeout)
    text = (evidence / (label + '.log')).read_text(errors='replace')
    print(label, result.returncode, text[-450:], flush=True)
    assert result.returncode == expected, (label, text[-8000:])
    return text

def test(label, files, expected=0, coverage=False, cwd=work):
    args = [python, '-m', 'pytest', *files, '-q', '--tb=short',
            '--junitxml=' + str(evidence / (label + '.xml'))]
    if coverage:
        args += ['--cov=tnco' if native else '--cov=zapbench', '--cov-branch',
                 '--cov-report=json:' + str(evidence / 'coverage.json')]
    run(label, args, expected, cwd)
    suites = list(ET.parse(evidence / (label + '.xml')).getroot().iter('testsuite'))
    counts = [sum(int(s.attrib.get(k, 0)) for s in suites)
              for k in ('tests', 'failures', 'errors', 'skipped')]
    summary[label] = counts
    print(label, counts, flush=True)
    return counts

assert subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=work, text=True).strip() == meta['head']
run('versions', [python, '-m', 'pip', 'freeze'])
run('test-dependency-check', [python, '-m', 'pip', 'check'])
if native:
    run('native-core-import', [python, '-c', 'import tnco_core; print(tnco_core.__file__)'])
existing = (['tests/test_utils.py::test_OrderedFrozenSet'] if native else
            ['zapbench/ts_forecasting/data_source_test.py'])
focused = [meta['test']]
try:
    assert test('fixed-focused', focused, coverage=True) == ([28, 0, 0, 0] if native else [22, 0, 0, 0])
    prior = test('fixed-existing', existing)
    assert prior[0] >= (200 if native else 29) and prior[1:] == [0, 0, 0]
    source.write_bytes(subprocess.check_output(['git', 'show', meta['base'] + ':' + meta['source']], cwd=work))
    assert test('original-focused', focused, expected=1) == ([28, 18, 0, 0] if native else [22, 10, 0, 0])
    assert test('original-existing', existing) == prior
finally:
    source.write_bytes(fixed)
assert test('restored-focused', focused) == ([28, 0, 0, 0] if native else [22, 0, 0, 0])
run('tracked-source-restored', ['git', 'diff', '--exit-code'])
run('patch-check', ['git', 'diff', '--check', meta['base']])
if native:
    run('repository-ruff', [python, '-m', 'ruff', 'check', 'tnco', 'tests'])
    assert not run('changed-file-yapf', [python, '-m', 'yapf', '--style=google', '-d', meta['source'], meta['test']]).strip()
    run('changed-file-isort', [python, '-m', 'isort', '--check-only', meta['source'], meta['test']])
    run('source-docformatter', [python, '-m', 'docformatter', '--check', meta['source']])
else:
    run('correctness-lint', [python, '-m', 'ruff', 'check', '--select', 'E9,F63,F7,F82', meta['source'], meta['test']])
    run('test-format', [python, '-m', 'pyink', '--target-version', 'py311', '--check', meta['test']])
    run('package-build', [python, '-m', 'build', '--outdir', str(evidence / 'dist')])
    wheel, = (evidence / 'dist').glob('*.whl')
    run('install-wheel', [python, '-m', 'pip', 'install', '--no-deps', str(wheel)])
with tempfile.TemporaryDirectory() as directory:
    outside = Path(directory)
    copied = outside / Path(meta['test']).name
    shutil.copyfile(work / meta['test'], copied)
    package = 'tnco' if native else 'zapbench'
    code = f"import {package}; from pathlib import Path; p=Path({package}.__file__).resolve(); print(p); assert not p.is_relative_to(Path({str(work)!r}))"
    run('installed-import', [python, '-c', code], cwd=outside)
    assert test('installed-focused', [str(copied)], cwd=outside) == ([28, 0, 0, 0] if native else [22, 0, 0, 0])
(evidence / 'summary.json').write_text(json.dumps(summary, indent=2))
print('EXACT SOURCE VERIFIED', meta['head'], flush=True)

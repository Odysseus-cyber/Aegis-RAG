"""Deploy one complete published Aegis-RAG release into isolated local state.

No source build, host PDF, existing Chroma or native telemetry is used.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import tarfile
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

from release_manifest import REPOSITORY, validate_manifest

ROOT = Path(__file__).resolve().parents[1]
STATE = ROOT / '.runtime' / 'aegis-demo'
API = 'http://127.0.0.1:15173/api'
DEMO_DOCUMENT = Path('aegis-demo.pdf').stem


def command(*args, capture=False, env=None, check=True):
    return subprocess.run(args, check=check, text=True, capture_output=capture, env=env, cwd=ROOT)


def compose(config, *args, **kwargs):
    return command('docker', 'compose', '-f', str(config), *args, **kwargs)


def save(path, value):
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(value, indent=2) + '\n')
    temporary.replace(path)


def request(url, data=None, timeout=600):
    body = None if data is None else json.dumps(data).encode()
    return urllib.request.urlopen(urllib.request.Request(
        url, data=body, headers={'Content-Type': 'application/json'}), timeout=timeout)


def read_json(url, data=None):
    with request(url, data) as response:
        return json.load(response)


def download(url, destination):
    with urllib.request.urlopen(url, timeout=120) as response, destination.open('wb') as output:
        shutil.copyfileobj(response, output)


def unpack_bundle(archive, destination):
    with tarfile.open(archive) as bundle:
        for item in bundle.getmembers():
            target = destination / item.name
            if not target.resolve().is_relative_to(destination.resolve()) or not (item.isfile() or item.isdir()):
                raise ValueError('Unsafe deployment bundle entry')
        bundle.extractall(destination, filter='data')


def prepare(version):
    if not re.fullmatch(r'[0-9a-f]{40}', version):
        raise ValueError('VERSION must be a full 40-character commit SHA from a successful release')
    destination = STATE / 'releases' / f'{version}-{uuid.uuid4().hex[:8]}'
    destination.mkdir(parents=True)
    base = f'https://github.com/{REPOSITORY}/releases/download/sha-{version}'
    download(base + '/delivery.json', destination / 'delivery.json')
    manifest = validate_manifest(json.loads((destination / 'delivery.json').read_text()), version)
    download(base + '/deployment.tar.gz', destination / 'deployment.tar.gz')
    unpack_bundle(destination / 'deployment.tar.gz', destination)
    for directory in ('llms-txt', 'telemetry', 'chroma', 'prometheus', 'grafana', 'reports'):
        (STATE / directory).mkdir(parents=True, exist_ok=True)
    fixture = destination / 'tests' / 'fixtures' / 'aegis-demo.pdf'
    if not fixture.is_file():
        raise ValueError('Release is missing its synthetic PDF acceptance fixture')
    # Release-specific read-only inputs restore with the selected image set on rollback.
    env = os.environ.copy()
    env.update(AEGIS_STATE=str(STATE), AEGIS_DATA=str(fixture.parent),
               LOCAL_UID=str(os.getuid()), LOCAL_GID=str(os.getgid()))
    env.update({f'IMAGE_{name.upper()}': image['image'] + '@' + image['digest']
                for name, image in manifest['images'].items()})
    output = compose(destination / 'docker-compose.release.yml', '--profile', 'drift',
                     'config', '--format', 'json', capture=True, env=env).stdout
    config = destination / 'compose.json'
    save(config, json.loads(output))
    return {'manifest': manifest, 'config': str(config)}


def preflight(record):
    config = record['config']
    compose(config, '--profile', 'drift', 'pull')
    for name, image in record['manifest']['images'].items():
        reference = image['image'] + '@' + image['digest']
        details = json.loads(command('docker', 'image', 'inspect', reference, capture=True).stdout)[0]
        labels = details.get('Config', {}).get('Labels', {}) or {}
        if labels.get('org.opencontainers.image.revision') != record['manifest']['commit_sha']:
            raise RuntimeError(f'{name} OCI revision does not match the delivery manifest')
    # Check connectivity from exactly the image/network used by the application.
    probe = (
        "import json,urllib.request; "
        "d=json.load(urllib.request.urlopen('http://host.docker.internal:11434/api/tags',timeout=10)); "
        "models={m['name'] for m in d['models']}; "
        "assert 'gemma3:1b' in models and any(m in models for m in "
        "['nomic-embed-text','nomic-embed-text:latest']), 'Required Ollama models missing'"
    )
    compose(config, 'run', '--rm', '--no-deps', '--entrypoint', 'python', 'backend', '-c', probe)


def parse_stream(stream):
    events = []
    for frame in stream.replace('\r\n', '\n').split('\n\n'):
        kind, data = 'message', []
        for line in frame.splitlines():
            if line.startswith('event:'):
                kind = line[6:].strip()
            elif line.startswith('data:'):
                data.append(line[5:].strip())
        if data:
            events.append((kind, json.loads('\n'.join(data))))
    errors = [data for kind, data in events if kind == 'error']
    if errors:
        raise RuntimeError(f'Model stream failed: {errors}')
    if not any(kind == 'done' for kind, _ in events):
        raise RuntimeError('Model stream ended without done')
    citations = [data for kind, data in events if kind == 'citations']
    answer = ''.join(data.get('token', '') for _, data in events if isinstance(data, dict))
    if not answer.strip() or not citations:
        raise RuntimeError('Answer or citations missing')
    return answer, citations


def wait_http(url, timeout=120):
    deadline = time.monotonic() + timeout
    while True:
        try:
            with request(url, timeout=5) as response:
                if response.status == 200:
                    return
                raise RuntimeError(f'Unhealthy service: {url}')
        except (urllib.error.URLError, TimeoutError, ConnectionError):
            if time.monotonic() >= deadline:
                raise
            time.sleep(2)


def verify(record):
    config = record['config']
    for url in (API + '/health', 'http://127.0.0.1:19090/-/ready',
                'http://127.0.0.1:13000/api/health', 'http://127.0.0.1:19091/-/ready'):
        wait_http(url)
    version = read_json(API + '/version')
    if version['commit_sha'] != record['manifest']['commit_sha']:
        raise RuntimeError('Deployed backend commit does not match the delivery manifest')
    previous = None
    for _ in range(2):
        read_json(API + '/admin/ingest', {})
        docs = read_json(API + '/admin/documents')['documents']
        count = compose(config, 'exec', '-T', 'backend', 'python', '-c',
                        'from app.rag.ingest import _get_collection,_chroma_client; '
                        'print(_get_collection(_chroma_client()).count())', capture=True).stdout.strip()
        snapshot = (docs, int(count))
        if DEMO_DOCUMENT not in docs or int(count) <= 0 or (previous and snapshot != previous):
            raise RuntimeError('Repeated PDF ingestion changed counts or lost the fixture')
        previous = snapshot
    conversation = str(uuid.uuid4())
    history, feedback_ids = [], []
    for query in ('How frequently must access reviews occur?', 'Who owns that process and how long is evidence retained?'):
        with request(API + '/chat', {'conversation_id': conversation, 'message': query,
                                    'history': history, 'doc_filter': [DEMO_DOCUMENT]}) as response:
            message_id = response.headers.get('X-Message-Id')
            answer, citations = parse_stream(response.read().decode())
        if not message_id:
            raise RuntimeError('Missing server message ID')
        # Citation metadata must identify the selected PDF, not an unrelated source.
        if DEMO_DOCUMENT not in json.dumps(citations):
            raise RuntimeError('Citations do not reference the selected document')
        history.extend([{'role': 'user', 'content': query}, {'role': 'assistant', 'content': answer}])
        feedback_ids.append(read_json(API + '/feedback', {'message_id': message_id, 'rating': 1})['feedback_id'])
    messages = read_json(API + f'/conversations/{conversation}')['messages']
    if len(messages) != 4:
        raise RuntimeError('Conversation messages were not persisted')
    feedback_check = (
        "import sqlite3,sys; from app.config import settings; "
        "db=sqlite3.connect(settings.telemetry_db_path); "
        "rows=db.execute('SELECT f.id FROM feedback f JOIN messages m ON f.message_id=m.id '"
        "'WHERE m.conversation_id=? AND m.role=\"assistant\"',(sys.argv[1],)).fetchall(); "
        "assert {r[0] for r in rows} == set(sys.argv[2:]), rows"
    )
    compose(config, 'exec', '-T', 'backend', 'python', '-c', feedback_check, conversation, *feedback_ids)
    report = {'status': 'passed', 'commit_sha': version['commit_sha'], 'conversation_id': conversation,
              'documents': previous[0], 'chunks': previous[1], 'feedback_ids': feedback_ids}
    save(STATE / 'reports' / 'acceptance.json', report)
    print(json.dumps(report, indent=2))
    return report


def collect_logs(record):
    result = compose(record['config'], 'logs', '--no-color', capture=True, check=False)
    (STATE / 'reports' / 'deployment-failure.log').write_text(result.stdout + result.stderr)


def activate(record):
    compose(record['config'], 'up', '-d', '--wait', '--wait-timeout', '240', '--remove-orphans')


def restore(record):
    activate(record)
    if read_json(API + '/version')['commit_sha'] != record['manifest']['commit_sha']:
        raise RuntimeError('Rollback version check failed')


def deploy(record, previous=None):
    # Pull/preflight failure does not touch the currently running application.
    preflight(record)
    try:
        activate(record)
        verify(record)
    except Exception:
        collect_logs(record)
        if previous:
            restore(previous)
        else:
            compose(record['config'], 'down', check=False)
        raise
    if previous and (not previous.get('manifest') or
                     previous['manifest']['commit_sha'] != record['manifest']['commit_sha']):
        save(STATE / 'previous.json', previous)
    save(STATE / 'current.json', record)
    # Evaluation is reporting only. Functional acceptance above controls promotion.
    evaluate(record)


def evaluate(record):
    result = compose(record['config'], 'run', '--rm', '--no-deps', 'drift-job',
                     '--trigger', 'adhoc', '--pipeline-version', record['manifest']['commit_sha'],
                     '--report', '/app/reports/drift.json', check=False)
    print(f'Evaluation exit code: {result.returncode} (0 completed/insufficient, 1 alert, 2 error). '
          'This report does not roll back a functionally verified deployment.')
    return result.returncode


def current():
    path = STATE / 'current.json'
    if not path.exists():
        raise ValueError('No verified deployment. Run deploy-demo with a published commit first.')
    return json.loads(path.read_text())


def rollback():
    old = current()
    previous_path = STATE / 'previous.json'
    if not previous_path.exists():
        raise ValueError('No previous verified release to roll back to')
    previous = json.loads(previous_path.read_text())
    try:
        restore(previous)
        verify(previous)
    except Exception:
        restore(old)
        raise
    save(STATE / 'current.json', previous)
    save(previous_path, old)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['deploy', 'verify', 'rollback', 'evaluate'])
    parser.add_argument('--version', default='')
    args = parser.parse_args()
    STATE.mkdir(parents=True, exist_ok=True)
    lock = STATE / 'operation.lock'
    try:
        descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError:
        parser.error(f'Another operation is active. If it crashed, remove {lock} after checking processes.')
    try:
        os.close(descriptor)
        if args.action == 'deploy':
            previous = current() if (STATE / 'current.json').exists() else None
            deploy(prepare(args.version), previous)
        elif args.action == 'verify':
            verify(current())
        elif args.action == 'rollback':
            rollback()
        else:
            return evaluate(current())
    finally:
        lock.unlink(missing_ok=True)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

"""Delivery tests use isolated state and fake commands; never touch a local deployment."""
import importlib.util
import io
import json
import sys
import tarfile
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / 'scripts'
sys.path.insert(0, str(SCRIPTS))
spec = importlib.util.spec_from_file_location('deploy_demo', SCRIPTS / 'deploy_demo.py')
deploy = importlib.util.module_from_spec(spec)
spec.loader.exec_module(deploy)
from release_manifest import (  # noqa: E402
    IMAGE_ROOT,
    STORAGE_NAMESPACE,
    assemble,
    validate_manifest,
)


def manifest():
    return {'schema_version': 1, 'storage_namespace': STORAGE_NAMESPACE, 'commit_sha': 'a' * 40, 'images': {
        name: {'image': f'{IMAGE_ROOT}/{name}', 'digest': 'sha256:' + '1' * 64}
        for name in ('backend', 'frontend', 'drift')}}


def record(config='new', sha='a' * 40):
    value = manifest()
    value['commit_sha'] = sha
    return {'config': config, 'manifest': value, 'storage_namespace': STORAGE_NAMESPACE}


def test_manifest_requires_complete_matching_set(tmp_path):
    value = manifest()
    assert validate_manifest(value, 'a' * 40) == value
    with pytest.raises(ValueError, match='match'):
        validate_manifest(value, 'b' * 40)
    value['images'].pop('drift')
    with pytest.raises(ValueError, match='Incomplete'):
        validate_manifest(value)
    for name, image in manifest()['images'].items():
        (tmp_path / f'{name}.json').write_text(json.dumps(image))
    assert assemble(tmp_path, 'a' * 40, 'https://example.com/run')['images'] == manifest()['images']
    (tmp_path / 'drift.json').unlink()
    with pytest.raises(FileNotFoundError):
        assemble(tmp_path, 'a' * 40, '')


@pytest.mark.parametrize('image,digest', [('untrusted.example/backend', 'sha256:' + '1'*64),
                                         (f'{IMAGE_ROOT}/backend', 'latest')])
def test_manifest_rejects_non_digest_or_wrong_registry(image, digest):
    value = manifest()
    value['images']['backend'] = {'image': image, 'digest': digest}
    with pytest.raises(ValueError, match='Invalid image'):
        validate_manifest(value)


@pytest.mark.parametrize('name,kind', [('../outside', 'file'), ('link', 'symlink')])
def test_bundle_rejects_traversal_and_links(tmp_path, name, kind):
    archive = tmp_path / 'archive.tar.gz'
    with tarfile.open(archive, 'w:gz') as bundle:
        item = tarfile.TarInfo(name)
        if kind == 'symlink':
            item.type = tarfile.SYMTYPE
            item.linkname = '/tmp/outside'
        bundle.addfile(item, io.BytesIO(b''))
    with pytest.raises(ValueError, match='Unsafe'):
        deploy.unpack_bundle(archive, tmp_path / 'target')


def test_stream_requires_done_and_preserves_tokens():
    stream = ('event: citations\r\ndata: {"citations":[{"doc_name":"aegis-demo"}]}\r\n\r\n'
              'data: {"token":"Hello "}\r\n\r\ndata: {"token":"world"}\r\n\r\n'
              'event: done\r\ndata: {}\r\n\r\n')
    assert deploy.parse_stream(stream)[0] == 'Hello world'
    with pytest.raises(RuntimeError, match='without done'):
        deploy.parse_stream('data: {"token":"truncated"}\n\n')
    with pytest.raises(RuntimeError, match='failed'):
        deploy.parse_stream('event: error\ndata: {"message":"connection failed"}\n\n')


@pytest.fixture
def operations(monkeypatch, tmp_path):
    monkeypatch.setattr(deploy, 'STATE', tmp_path)
    calls = []
    for name in ('preflight', 'activate', 'verify', 'restore', 'collect_logs', 'evaluate'):
        monkeypatch.setattr(deploy, name, lambda record, name=name: calls.append((name, record)))
    monkeypatch.setattr(deploy, 'compose', lambda *args, **kwargs: calls.append(('compose', args)))
    return calls, tmp_path


def test_success_promotes_only_after_verification_and_evaluation_does_not_block(operations, monkeypatch):
    calls, state = operations
    previous, candidate = record('old', 'b' * 40), record('new')
    monkeypatch.setattr(deploy, 'evaluate', lambda record: 2)
    deploy.commit_state(previous, None)
    deploy.deploy(candidate)
    assert [name for name, _ in calls] == ['preflight', 'activate', 'verify']
    assert json.loads((state / 'state.json').read_text())['current'] == candidate
    assert json.loads((state / 'state.json').read_text())['previous'] == previous


def test_failed_verify_restores_previous_without_promoting(operations, monkeypatch):
    calls, state = operations
    previous, candidate = record('old', 'b' * 40), record('new')
    deploy.commit_state(previous, None)
    monkeypatch.setattr(deploy, 'verify', lambda record: (_ for _ in ()).throw(RuntimeError('failed')))
    with pytest.raises(RuntimeError, match='failed'):
        deploy.deploy(candidate)
    assert calls[-1] == ('restore', previous)
    assert json.loads((state / 'state.json').read_text())['current'] == previous


def test_preflight_failure_leaves_running_release_untouched(operations, monkeypatch):
    calls, state = operations
    monkeypatch.setattr(deploy, 'preflight', lambda record: (_ for _ in ()).throw(RuntimeError('download')))
    with pytest.raises(RuntimeError, match='download'):
        deploy.deploy(record('new'))
    assert calls == []
    assert not (state / 'state.json').exists()


def test_first_deployment_failure_stops_services_without_deleting_volumes(operations, monkeypatch):
    calls, state = operations
    monkeypatch.setattr(deploy, 'verify', lambda record: (_ for _ in ()).throw(RuntimeError('failed')))
    with pytest.raises(RuntimeError):
        deploy.deploy(record('new'))
    assert calls[-1] == ('compose', ('new', 'down'))
    assert not (state / 'state.json').exists()


def test_manual_rollback_swaps_verified_records(operations):
    _, state = operations
    deploy.commit_state(record('new'), record('old', 'b' * 40))
    deploy.rollback()
    assert json.loads((state / 'state.json').read_text())['current'] == record('old', 'b' * 40)
    assert json.loads((state / 'state.json').read_text())['previous'] == record('new')


def test_preflight_rejects_wrong_oci_revision_before_starting(monkeypatch):
    from types import SimpleNamespace

    calls = []
    monkeypatch.setattr(deploy, 'compose', lambda *args, **kwargs: calls.append(args))
    monkeypatch.setattr(deploy, 'command', lambda *args, **kwargs: SimpleNamespace(
        stdout=json.dumps([{'Config': {'Labels': {'org.opencontainers.image.revision': 'b' * 40}}}])))
    with pytest.raises(RuntimeError, match='OCI revision'):
        deploy.preflight(record('candidate'))
    assert calls == [('candidate', '--profile', 'drift', 'pull', '--policy', 'missing')]


def test_redeploy_same_commit_preserves_last_distinct_version(operations):
    _, state = operations
    old = record('older', 'b' * 40)
    same = record('same')
    candidate = record('candidate')
    deploy.commit_state(same, old)
    deploy.deploy(candidate)
    assert json.loads((state / 'state.json').read_text())['previous'] == old


def test_demo_filter_uses_ingestion_document_stem(monkeypatch):
    from unittest.mock import Mock

    from app.rag import ingest

    fixture = Path(__file__).parent / 'fixtures' / 'aegis-demo.pdf'
    upsert = Mock(return_value=(1, 0))
    monkeypatch.setattr(ingest, '_embed', lambda texts: [[1., 0.] for _ in texts])
    monkeypatch.setattr(ingest, '_upsert_chunks', upsert)
    monkeypatch.setattr(ingest, '_write_llms_txt', Mock())
    ingest.ingest_pdf(fixture, Mock(), 'test')
    chunks = upsert.call_args.args[1]
    assert chunks
    assert {chunk.doc_name for chunk in chunks} == {deploy.DEMO_DOCUMENT}


def test_service_readiness_retries_startup_connection_failure(monkeypatch):
    import urllib.error
    from unittest.mock import MagicMock, Mock

    response = MagicMock()
    response.__enter__.return_value.status = 200
    request = Mock(side_effect=[urllib.error.URLError('starting'), response])
    monkeypatch.setattr(deploy, 'request', request)
    monkeypatch.setattr(deploy.time, 'sleep', lambda seconds: None)
    deploy.wait_http('http://localhost/health')
    assert request.call_count == 2
    request.assert_called_with('http://localhost/health', timeout=5)


def test_activate_refreshes_proxy_after_backend_ready_and_waits_for_http(monkeypatch):
    calls = []
    monkeypatch.setattr(deploy, 'compose', lambda *args, **kwargs: calls.append(('compose', args)))
    monkeypatch.setattr(deploy, 'wait_http', lambda url: calls.append(('health', url)))
    deploy.activate(record('release.json'))
    assert calls == [
        ('compose', ('release.json', 'up', '-d', '--wait', '--wait-timeout', '240', '--remove-orphans')),
        ('compose', ('release.json', 'restart', 'frontend')),
        ('health', deploy.API + '/health'),
    ]


@pytest.mark.parametrize('first_error', [
    deploy.urllib.error.URLError('TLS EOF'), TimeoutError('timeout'), deploy.ssl.SSLEOFError('TLS stream ended'),
])
def test_download_retries_connection_failure_then_publishes_complete_file(tmp_path, monkeypatch, first_error):
    from unittest.mock import Mock

    destination = tmp_path / 'delivery.json'
    response = io.BytesIO(b'complete')
    response.headers = {'Content-Length': '8'}
    urlopen = Mock(side_effect=[first_error, response])
    monkeypatch.setattr(deploy.urllib.request, 'urlopen', urlopen)
    monkeypatch.setattr(deploy.time, 'sleep', lambda seconds: None)
    deploy.download('https://example.test/delivery.json', destination)
    assert destination.read_bytes() == b'complete'
    assert urlopen.call_count == 2
    assert not destination.with_name('delivery.json.part').exists()


def test_download_does_not_publish_partial_response_and_retries_cleanly(tmp_path, monkeypatch):
    destination = tmp_path / 'deployment.tar.gz'
    destination.write_bytes(b'previous complete release')
    calls = []

    class InterruptedResponse(io.BytesIO):
        headers = {'Content-Length': '100'}

        def read(self, size=-1):
            if self.tell():
                raise deploy.urllib.error.URLError('connection ended')
            return super().read(size)

    def urlopen(*args, **kwargs):
        calls.append(args)
        # The original artifact survives both an in-flight and failed replacement.
        assert destination.read_bytes() == b'previous complete release'
        if len(calls) == 1:
            return InterruptedResponse(b'partial')
        assert not destination.with_name(destination.name + '.part').exists()
        response = io.BytesIO(b'new complete release')
        response.headers = {}
        return response

    monkeypatch.setattr(deploy.urllib.request, 'urlopen', urlopen)
    monkeypatch.setattr(deploy.time, 'sleep', lambda seconds: None)
    deploy.download('https://example.test/deployment.tar.gz', destination)
    assert destination.read_bytes() == b'new complete release'
    assert len(calls) == 2
    assert not destination.with_name(destination.name + '.part').exists()


def test_download_exhaustion_raises_without_replacing_existing_file(tmp_path, monkeypatch):
    from unittest.mock import Mock

    destination = tmp_path / 'delivery.json'
    destination.write_bytes(b'previous')
    error = deploy.urllib.error.URLError('network remains unavailable')
    urlopen = Mock(side_effect=error)
    monkeypatch.setattr(deploy.urllib.request, 'urlopen', urlopen)
    monkeypatch.setattr(deploy.time, 'sleep', lambda seconds: None)
    with pytest.raises(deploy.urllib.error.URLError, match='network remains unavailable'):
        deploy.download('https://example.test/delivery.json', destination)
    assert urlopen.call_count == 3
    assert destination.read_bytes() == b'previous'
    assert not destination.with_name(destination.name + '.part').exists()


def test_download_rejects_silent_short_body(tmp_path, monkeypatch):
    calls = []

    def urlopen(*args, **kwargs):
        calls.append(args)
        response = io.BytesIO(b'short')
        response.headers = {'Content-Length': '100'}
        return response

    monkeypatch.setattr(deploy.urllib.request, 'urlopen', urlopen)
    monkeypatch.setattr(deploy.time, 'sleep', lambda seconds: None)
    destination = tmp_path / 'deployment.tar.gz'
    with pytest.raises(deploy.urllib.error.URLError, match='Content-Length'):
        deploy.download('https://example.test/deployment.tar.gz', destination)
    assert len(calls) == 3
    assert not destination.exists()
    assert not destination.with_name(destination.name + '.part').exists()


@pytest.mark.parametrize('namespace', [None, 'obsolete-namespace'])
def test_manifest_rejects_missing_or_different_storage_namespace(namespace):
    value = manifest()
    if namespace is None:
        value.pop('storage_namespace')
    else:
        value['storage_namespace'] = namespace
    with pytest.raises(ValueError, match='storage namespace'):
        validate_manifest(value)


def test_assembled_manifest_declares_storage_namespace(tmp_path):
    for name, image in manifest()['images'].items():
        (tmp_path / f'{name}.json').write_text(json.dumps(image))
    value = assemble(tmp_path, 'a' * 40, 'https://example.com/run')
    assert value['storage_namespace'] == STORAGE_NAMESPACE


@pytest.mark.parametrize('target', ['candidate', 'previous'])
@pytest.mark.parametrize('location', ['record', 'manifest'])
@pytest.mark.parametrize('namespace', [None, 'obsolete-namespace'])
def test_deploy_rejects_incompatible_state_before_preflight(operations, target, location, namespace):
    calls, state = operations
    candidate, previous = record('new'), record('old', 'b' * 40)
    value = candidate if target == 'candidate' else previous
    subject = value if location == 'record' else value['manifest']
    if namespace is None:
        subject.pop('storage_namespace')
    else:
        subject['storage_namespace'] = namespace
    deploy.commit_state(previous, None)
    before = (state / 'state.json').read_bytes()
    with pytest.raises(ValueError, match='storage namespace'):
        deploy.deploy(candidate)
    assert not calls
    assert (state / 'state.json').read_bytes() == before


@pytest.mark.parametrize('target', ['current', 'previous'])
def test_rollback_rejects_incompatible_records_before_service_changes(operations, target):
    calls, state = operations
    records = {'current': record('new'), 'previous': record('old', 'b' * 40)}
    records[target]['manifest'].pop('storage_namespace')
    deploy.commit_state(records['current'], records['previous'])
    with pytest.raises(ValueError, match='storage namespace'):
        deploy.rollback()
    assert not calls
    for name, value in records.items():
        assert json.loads((state / 'state.json').read_text())[name] == value


def test_first_new_namespace_release_has_no_ordinary_rollback(operations):
    calls, state = operations
    deploy.deploy(record('new'))
    calls.clear()
    with pytest.raises(ValueError, match='first migrated release'):
        deploy.rollback()
    assert not calls


@pytest.mark.parametrize('legacy_file', ['current.json', 'previous.json'])
def test_first_release_rejects_legacy_deployment_state(operations, legacy_file):
    calls, state = operations
    deploy.save(state / legacy_file, {'config': 'archive-only'})
    with pytest.raises(ValueError, match='Legacy deployment state'):
        deploy.deploy(record('new'))
    assert not calls
    assert (state / legacy_file).exists()
    assert not (state / 'state.json').exists()


def test_log_collection_failure_still_restores_previous(operations, monkeypatch):
    calls, state = operations
    previous = record('old', 'b' * 40)
    deploy.commit_state(previous, None)
    monkeypatch.setattr(deploy, 'verify', lambda value: (_ for _ in ()).throw(RuntimeError('acceptance failed')))
    monkeypatch.setattr(deploy, 'collect_logs', lambda value: (_ for _ in ()).throw(OSError('no logs')))
    with pytest.raises(RuntimeError, match='acceptance failed'):
        deploy.deploy(record('new'))
    assert calls[-1] == ('restore', previous)
    assert json.loads((state / 'state.json').read_text())['current'] == previous


def test_failed_manual_rollback_restores_current_and_keeps_records(operations, monkeypatch):
    calls, state = operations
    candidate, previous = record('new'), record('old', 'b' * 40)
    deploy.commit_state(candidate, previous)
    monkeypatch.setattr(deploy, 'verify', lambda value: (_ for _ in ()).throw(RuntimeError('acceptance failed')))
    with pytest.raises(RuntimeError, match='acceptance failed'):
        deploy.rollback()
    assert calls == [('restore', previous), ('restore', candidate)]
    assert json.loads((state / 'state.json').read_text())['current'] == candidate
    assert json.loads((state / 'state.json').read_text())['previous'] == previous


def test_incompatible_release_download_never_creates_data_directories(tmp_path, monkeypatch):
    monkeypatch.setattr(deploy, 'STATE', tmp_path)
    downloads = []

    def download(url, destination):
        downloads.append(url)
        value = manifest()
        value.pop('storage_namespace')
        destination.write_text(json.dumps(value))

    monkeypatch.setattr(deploy, 'download', download)
    monkeypatch.setattr(deploy, 'compose', lambda *args, **kwargs: pytest.fail('must not call compose'))
    with pytest.raises(ValueError, match='storage namespace'):
        deploy.prepare('a' * 40)
    assert len(downloads) == 1
    assert {path.name for path in tmp_path.iterdir() if path.is_dir()} == {'releases'}


@pytest.mark.parametrize('has_previous', [False, True])
def test_deployment_state_commit_failure_restores_service_and_old_state(operations, monkeypatch, has_previous):
    calls, state = operations
    previous = record('old', 'b' * 40)
    if has_previous:
        deploy.commit_state(previous, record('older', 'c' * 40))
    original = (state / 'state.json').read_bytes() if has_previous else None
    replace = Path.replace

    def fail_state_replace(path, target):
        if Path(target) == state / 'state.json':
            raise OSError('state disk failure')
        return replace(path, target)

    monkeypatch.setattr(Path, 'replace', fail_state_replace)
    with pytest.raises(OSError, match='state disk failure'):
        deploy.deploy(record('new'))
    if has_previous:
        assert calls[-1] == ('restore', previous)
        assert (state / 'state.json').read_bytes() == original
    else:
        assert calls[-1] == ('compose', ('new', 'down'))
        assert not (state / 'state.json').exists()
    assert not any(name == 'evaluate' for name, _ in calls)


def test_rollback_state_commit_failure_restores_service_and_both_records(operations, monkeypatch):
    calls, state = operations
    active, previous = record('new'), record('old', 'b' * 40)
    deploy.commit_state(active, previous)
    original = (state / 'state.json').read_bytes()
    replace = Path.replace

    def fail_state_replace(path, target):
        if Path(target) == state / 'state.json':
            raise OSError('state disk failure')
        return replace(path, target)

    monkeypatch.setattr(Path, 'replace', fail_state_replace)
    with pytest.raises(OSError, match='state disk failure'):
        deploy.rollback()
    assert calls == [('restore', previous), ('verify', previous), ('restore', active)]
    assert (state / 'state.json').read_bytes() == original


def test_grafana_password_is_private_random_reused_and_never_printed(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(deploy, 'STATE', tmp_path)
    password = deploy.grafana_password()
    path = tmp_path / 'grafana-admin-password'
    assert len(password) >= 40
    assert path.read_text().strip() == password
    assert path.stat().st_mode & 0o777 == 0o600
    path.chmod(0o644)
    assert deploy.grafana_password() == password
    assert path.stat().st_mode & 0o777 == 0o600
    assert capsys.readouterr() == ('', '')


def test_empty_existing_grafana_password_is_not_silently_replaced(tmp_path, monkeypatch):
    monkeypatch.setattr(deploy, 'STATE', tmp_path)
    path = tmp_path / 'grafana-admin-password'
    path.write_text('')
    with pytest.raises(ValueError, match='password file is empty'):
        deploy.grafana_password()
    assert path.read_text() == ''


def test_generated_compose_and_state_files_are_private(tmp_path):
    path = tmp_path / 'compose.json'
    deploy.save(path, {'services': {}})
    assert path.stat().st_mode & 0o777 == 0o600
    path.chmod(0o644)
    deploy.save(path, {'services': {}})
    assert path.stat().st_mode & 0o777 == 0o600

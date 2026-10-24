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
from release_manifest import IMAGE_ROOT, assemble, validate_manifest  # noqa: E402


def manifest():
    return {'schema_version': 1, 'commit_sha': 'a' * 40, 'images': {
        name: {'image': f'{IMAGE_ROOT}/{name}', 'digest': 'sha256:' + '1' * 64}
        for name in ('backend', 'frontend', 'drift')}}


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
    previous, candidate = {'config': 'old'}, {'config': 'new'}
    monkeypatch.setattr(deploy, 'evaluate', lambda record: 2)
    deploy.deploy(candidate, previous)
    assert [name for name, _ in calls] == ['preflight', 'activate', 'verify']
    assert json.loads((state / 'current.json').read_text()) == candidate
    assert json.loads((state / 'previous.json').read_text()) == previous


def test_failed_verify_restores_previous_without_promoting(operations, monkeypatch):
    calls, state = operations
    previous, candidate = {'config': 'old'}, {'config': 'new'}
    deploy.save(state / 'current.json', previous)
    monkeypatch.setattr(deploy, 'verify', lambda record: (_ for _ in ()).throw(RuntimeError('failed')))
    with pytest.raises(RuntimeError, match='failed'):
        deploy.deploy(candidate, previous)
    assert calls[-1] == ('restore', previous)
    assert json.loads((state / 'current.json').read_text()) == previous


def test_preflight_failure_leaves_running_release_untouched(operations, monkeypatch):
    calls, state = operations
    monkeypatch.setattr(deploy, 'preflight', lambda record: (_ for _ in ()).throw(RuntimeError('download')))
    with pytest.raises(RuntimeError, match='download'):
        deploy.deploy({'config': 'new'}, {'config': 'old'})
    assert calls == []
    assert not (state / 'current.json').exists()


def test_first_deployment_failure_stops_services_without_deleting_volumes(operations, monkeypatch):
    calls, state = operations
    monkeypatch.setattr(deploy, 'verify', lambda record: (_ for _ in ()).throw(RuntimeError('failed')))
    with pytest.raises(RuntimeError):
        deploy.deploy({'config': 'new'})
    assert calls[-1] == ('compose', ('new', 'down'))
    assert not (state / 'current.json').exists()


def test_manual_rollback_swaps_verified_records(operations):
    _, state = operations
    deploy.save(state / 'current.json', {'config': 'new'})
    deploy.save(state / 'previous.json', {'config': 'old'})
    deploy.rollback()
    assert json.loads((state / 'current.json').read_text()) == {'config': 'old'}
    assert json.loads((state / 'previous.json').read_text()) == {'config': 'new'}


def test_preflight_rejects_wrong_oci_revision_before_starting(monkeypatch):
    from types import SimpleNamespace

    calls = []
    monkeypatch.setattr(deploy, 'compose', lambda *args, **kwargs: calls.append(args))
    monkeypatch.setattr(deploy, 'command', lambda *args, **kwargs: SimpleNamespace(
        stdout=json.dumps([{'Config': {'Labels': {'org.opencontainers.image.revision': 'b' * 40}}}])))
    with pytest.raises(RuntimeError, match='OCI revision'):
        deploy.preflight({'config': 'candidate', 'manifest': manifest()})
    assert calls == [('candidate', '--profile', 'drift', 'pull')]


def test_redeploy_same_commit_preserves_last_distinct_version(operations):
    _, state = operations
    old = {'config': 'older', 'manifest': {'commit_sha': 'b' * 40}}
    same = {'config': 'same', 'manifest': manifest()}
    candidate = {'config': 'candidate', 'manifest': manifest()}
    deploy.save(state / 'previous.json', old)
    deploy.deploy(candidate, same)
    assert json.loads((state / 'previous.json').read_text()) == old


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
    deploy.activate({'config': 'release.json'})
    assert calls == [
        ('compose', ('release.json', 'up', '-d', '--wait', '--wait-timeout', '240', '--remove-orphans')),
        ('compose', ('release.json', 'restart', 'frontend')),
        ('health', deploy.API + '/health'),
    ]

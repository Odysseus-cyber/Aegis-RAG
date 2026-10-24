"""Archive tests use private temporary files, without starting an HTTP server."""
import hashlib
import io
import json
from types import SimpleNamespace

import pytest

from scripts import serve_storage_migration as helper

ORIGIN = 'http://127.0.0.1:15173'


@pytest.fixture
def archive(tmp_path):
    path = tmp_path / 'private-archive'
    path.mkdir()
    return path


def payload():
    return json.dumps({'format': 1, 'origin': ORIGIN, 'capturedAt': 'test',
                       'sourceKeys': {'conversations': 'source_list', 'active': 'source_active'},
                       'source': {'conversations': '[{"id":"会话","messages":[]}]', 'active': '"会话"'},
                       'target': {'conversations': None, 'active': None}}, ensure_ascii=False).encode()


def headers(raw):
    return {'Host': '127.0.0.1:15173', 'Origin': ORIGIN,
            'Content-Type': 'application/json', 'Content-Length': str(len(raw))}


def test_archive_is_private_exact_and_receipt_does_not_disclose_chat(archive):
    raw = payload()
    receipt = helper.save_snapshot(raw, ORIGIN, archive)
    saved = archive / receipt['receipt']
    assert saved.read_bytes() == raw
    assert saved.stat().st_mode & 0o777 == 0o600
    assert receipt == {'status': 'saved', 'receipt': saved.name, 'sha256': hashlib.sha256(raw).hexdigest(),
                       'bytes': len(raw), 'origin': ORIGIN}
    assert '会话' not in json.dumps(receipt, ensure_ascii=False)
    second = helper.save_snapshot(raw, ORIGIN, archive)
    assert second['receipt'] != receipt['receipt']
    assert saved.read_bytes() == raw


def test_existing_file_is_never_overwritten(archive, monkeypatch):
    monkeypatch.setattr(helper.uuid, 'uuid4', lambda: SimpleNamespace(hex='a' * 32))
    target = archive / ('browser-snapshot-' + 'a' * 32 + '.json')
    target.write_text('existing')
    with pytest.raises(FileExistsError):
        helper.save_snapshot(payload(), ORIGIN, archive)
    assert target.read_text() == 'existing'
    assert len(list(archive.iterdir())) == 1


@pytest.mark.parametrize('field,value', [('Host', 'evil.example:15173'), ('Origin', 'http://evil.example'),
                                        ('Origin', 'http://localhost:15173'), ('Content-Type', 'text/plain'),
                                        ('Content-Length', str(helper.MAX_BODY + 1)), ('Content-Length', '-1'),
                                        ('Content-Length', ''), ('Transfer-Encoding', 'chunked')])
def test_rejects_bad_http_envelope(field, value):
    request_headers = headers(payload())
    request_headers[field] = value
    with pytest.raises(ValueError):
        helper.validate_request('/migration-backup', request_headers, 15173)


def test_exact_route_and_missing_origin_rejected():
    with pytest.raises(ValueError):
        helper.validate_request('/migration-backup?filename=arbitrary', headers(payload()), 15173)
    request_headers = headers(payload())
    request_headers.pop('Origin')
    with pytest.raises(ValueError):
        helper.validate_request('/migration-backup', request_headers, 15173)


def test_wrong_snapshot_origin_and_internal_archive_rejected(archive):
    with pytest.raises(ValueError, match='origin'):
        helper.save_snapshot(payload(), 'http://localhost:15173', archive)
    with pytest.raises(ValueError, match='outside'):
        helper.save_snapshot(payload(), ORIGIN, helper.ROOT / '.runtime' / 'private')
    assert not list(archive.iterdir())


def test_write_failure_does_not_return_receipt_or_leave_partial_file(archive, monkeypatch):
    def fail(*args):
        raise OSError('disk failure')
    monkeypatch.setattr(helper.os, 'fsync', fail)
    with pytest.raises(OSError):
        helper.save_snapshot(payload(), ORIGIN, archive)
    assert not list(archive.iterdir())


def test_readback_mismatch_does_not_report_success(archive, monkeypatch):
    monkeypatch.setattr(helper.Path, 'read_bytes', lambda self: b'{}')
    with pytest.raises(OSError, match='verification'):
        helper.save_snapshot(payload(), ORIGIN, archive)


def test_handler_accepts_snapshot_without_running_server(archive):
    raw = payload()
    handler = object.__new__(helper.Handler)
    handler.path = '/migration-backup'
    handler.headers = headers(raw)
    handler.server = SimpleNamespace(server_port=15173, archive_dir=archive)
    handler.connection = SimpleNamespace(settimeout=lambda _: None)
    handler.rfile = io.BytesIO(raw)
    responses = []
    handler.respond = lambda code, data: responses.append((code, json.loads(data)))
    handler.do_POST()
    assert responses[0][0] == 200
    assert responses[0][1]['sha256'] == hashlib.sha256(raw).hexdigest()


def test_handler_short_body_cannot_create_backup(archive):
    raw = payload()
    handler = object.__new__(helper.Handler)
    handler.path = '/migration-backup'
    handler.headers = headers(raw)
    handler.server = SimpleNamespace(server_port=15173, archive_dir=archive)
    handler.connection = SimpleNamespace(settimeout=lambda _: None)
    handler.rfile = io.BytesIO(raw[:-10])
    responses = []
    handler.respond = lambda code, data: responses.append(code)
    handler.do_POST()
    assert responses == [400]
    assert not list(archive.iterdir())


@pytest.mark.parametrize('asset', list(helper.ASSETS))
def test_versioned_asset_urls_serve_current_module(asset):
    handler = object.__new__(helper.Handler)
    handler.path = asset + '?version=2'
    handler.headers = {'Host': '127.0.0.1:15173'}
    handler.server = SimpleNamespace(server_port=15173)
    responses = []
    handler.respond = lambda code, data, content_type=None: responses.append((code, data))
    handler.do_GET()
    assert responses == [(200, (helper.PUBLIC / asset.lstrip('/')).read_bytes())]


def test_asset_query_cannot_escape_allowed_paths():
    handler = object.__new__(helper.Handler)
    handler.path = '/../../.env?version=2'
    handler.headers = {'Host': '127.0.0.1:15173'}
    handler.server = SimpleNamespace(server_port=15173)
    responses = []
    handler.respond = lambda code, data, content_type=None: responses.append(code)
    handler.do_GET()
    assert responses == [404]

import { test } from 'vitest';
import { Buffer } from 'node:buffer';
import { TextEncoder } from 'node:util';
import assert from 'node:assert/strict';
import { webcrypto, createHash } from 'node:crypto';
import { archiveSnapshot } from '../public/storage-migration-backup.mjs';

const snapshot = { format: 1, origin: 'http://127.0.0.1:15173', source: { conversations: '中文消息' } };
const valid = () => ({ status: 'saved', receipt: `browser-snapshot-${'a'.repeat(32)}.json`,
  sha256: createHash('sha256').update(JSON.stringify(snapshot)).digest('hex'),
  bytes: Buffer.byteLength(JSON.stringify(snapshot)), origin: snapshot.origin });
const run = (receipt, status = true) => archiveSnapshot(snapshot, { crypto: webcrypto, TextEncoder,
  fetch: async (url, options) => {
    assert.equal(url, '/migration-backup');
    assert.equal(options.method, 'POST');
    assert.equal(options.body, JSON.stringify(snapshot));
    return { ok: status, json: async () => receipt };
  } });

test('verified receipt matches exact UTF-8 snapshot', async () => {
  assert.deepEqual(await run(valid()), valid());
});
for (const field of ['sha256', 'bytes', 'origin', 'receipt', 'status']) {
  test(`does not authorize migration for a mismatched ${field}`, async () => {
    await assert.rejects(run({ ...valid(), [field]: 'wrong' }), /未允许迁移/);
  });
}
test('ordinary published app without helper requires manual backup verification', async () => {
  await assert.rejects(run(null, false), /导出 \+ 上传备份验证/);
});
test('network failure does not authorize migration', async () => {
  await assert.rejects(archiveSnapshot(snapshot, { crypto: webcrypto, TextEncoder,
    fetch: async () => { throw new Error('offline'); } }), /offline/);
});

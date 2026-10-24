import { beforeEach, afterEach, expect, test, vi } from 'vitest';
const { document, localStorage, Event, URL, HTMLAnchorElement } = globalThis;
const archive = vi.hoisted(() => vi.fn());
vi.mock('../public/storage-migration-backup.mjs?version=2', () => ({ archiveSnapshot: archive }));
const element = (id) => document.getElementById(id);

beforeEach(async () => {
  vi.resetModules(); archive.mockReset(); localStorage.clear();
  document.body.innerHTML = `<span id="origin"></span><input id="source-conversations"><input id="source-active">
    <button id="inspect"></button><input id="backup" type="file" disabled><button id="archive" disabled></button>
    <button id="migrate" disabled></button><div id="status"></div>`;
  URL.createObjectURL = vi.fn(() => 'blob:backup'); URL.revokeObjectURL = vi.fn();
  vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {});
  vi.spyOn(globalThis, 'setTimeout').mockImplementation(() => 0);
  await import('../public/storage-migration-ui.mjs?version=2');
  element('source-conversations').value = 'source_sessions';
  element('source-active').value = 'source_active';
  localStorage.setItem('source_sessions', '[{"id":"s","messages":[]}]');
  localStorage.setItem('source_active', '"s"');
  element('inspect').click();
});
afterEach(() => vi.restoreAllMocks());
const flush = async () => { await Promise.resolve(); await Promise.resolve(); await Promise.resolve(); };

test('local helper failure leaves migration disabled and offers file backup validation', async () => {
  archive.mockRejectedValue(new Error('endpoint unavailable'));
  element('archive').click(); await flush();
  expect(element('migrate').disabled).toBe(true);
  expect(element('status').textContent).toContain('不能跳过备份');
  expect(localStorage.getItem('source_sessions')).not.toBeNull();
});

test('verified archive enables migration without changing storage yet', async () => {
  archive.mockResolvedValue({ receipt: 'private.json', bytes: 200 });
  element('archive').click(); await flush();
  expect(element('migrate').disabled).toBe(false);
  expect(element('status').textContent).toContain('已保存并读回核对');
  expect(localStorage.getItem('source_sessions')).not.toBeNull();
});

test('late receipt cannot authorize a changed source key', async () => {
  let finish;
  archive.mockImplementation(() => new Promise((resolve) => { finish = resolve; }));
  element('archive').click();
  element('source-active').value = 'different';
  element('source-active').dispatchEvent(new Event('input'));
  finish({ receipt: 'private.json', bytes: 200 }); await flush();
  expect(element('migrate').disabled).toBe(true);
  expect(element('status').textContent).toContain('快照已变化');
});

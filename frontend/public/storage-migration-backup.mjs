/** Verify the local helper's durable receipt against the exact submitted snapshot. */
export async function archiveSnapshot(snapshot, { fetch = globalThis.fetch, crypto = globalThis.crypto,
  TextEncoder = globalThis.TextEncoder } = {}) {
  const body = JSON.stringify(snapshot);
  const bytes = new TextEncoder().encode(body);
  const hash = await crypto.subtle.digest('SHA-256', bytes);
  const sha256 = Array.from(new Uint8Array(hash), (value) => value.toString(16).padStart(2, '0')).join('');
  const response = await fetch('/migration-backup', { method: 'POST',
    headers: { 'Content-Type': 'application/json' }, body });
  if (!response.ok) throw new Error('本机归档服务不可用或保存失败。请启动本机迁移辅助服务，或使用导出 + 上传备份验证；未允许迁移。');
  const receipt = await response.json();
  if (receipt.status !== 'saved' || receipt.sha256 !== sha256 || receipt.bytes !== bytes.length
    || receipt.origin !== snapshot.origin || !/^browser-snapshot-[a-f0-9]{32}\.json$/.test(receipt.receipt)) {
    throw new Error('归档回执与当前快照不一致；未允许迁移。请改用导出 + 上传备份验证。');
  }
  return receipt;
}

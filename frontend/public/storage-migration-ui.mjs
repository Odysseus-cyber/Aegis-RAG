const { document, location, localStorage, Blob, URL, setTimeout } = globalThis;

  import { snapshotStorage, migrateStorage } from './storage-migration.mjs';
  const byId = (id) => document.getElementById(id);
  byId('origin').textContent = location.origin;
  let snapshot = null;
  let verified = false;
  const status = (text) => { byId('status').textContent = text; };
  const reset = () => { snapshot = null; verified = false; byId('backup').disabled = true;
    byId('backup').value = ''; byId('migrate').disabled = true; };
  for (const id of ['source-conversations', 'source-active']) byId(id).addEventListener('input', reset);
  byId('inspect').addEventListener('click', () => {
    reset();
    try {
      snapshot = snapshotStorage({ storage: localStorage, origin: location.origin,
        sourceConversationKey: byId('source-conversations').value.trim(), sourceActiveKey: byId('source-active').value.trim() });
      const count = JSON.parse(snapshot.source.conversations ?? '[]').length;
      const blob = new Blob([JSON.stringify(snapshot, null, 2)], { type: 'application/json' });
      const url = URL.createObjectURL(blob);
      const link = document.createElement('a'); link.href = url;
      link.download = `aegis-rag-browser-backup-${location.hostname}-${location.port || 'default'}-${Date.now()}.json`;
      document.body.appendChild(link); link.click(); link.remove();
      setTimeout(() => URL.revokeObjectURL(url), 30000);
      byId('backup').disabled = false;
      status(`发现 ${count} 条源会话。备份下载已触发；请确认文件保存，再选择同一文件验证。尚未修改存储。`);
    } catch (error) { status(error.message); }
  });
  byId('backup').addEventListener('change', async () => {
    verified = false; byId('migrate').disabled = true;
    try {
      const file = byId('backup').files[0]; if (!file || !snapshot) return;
      const parsed = JSON.parse(await file.text());
      if (JSON.stringify(parsed) !== JSON.stringify(snapshot)) throw new Error('所选备份与当前快照不一致，请重新导出。');
      verified = true; byId('migrate').disabled = false;
      status('备份已读回验证。可以迁移；目标数据有冲突时会保留两份并停止。');
    } catch (error) { status(error.message); }
  });
  byId('migrate').addEventListener('click', async () => {
    byId('migrate').disabled = true;
    try {
      const result = await migrateStorage({ storage: localStorage, origin: location.origin, snapshot,
        exportBackup: async (value) => verified && value === snapshot });
      status(result.status === 'unchanged' ? '没有待迁移的源数据。现有目标数据保持不变。'
        : `迁移成功，已核对 ${result.migratedKeys} 个目标键并删除对应源键。会话与消息 ID 保持不变。请保留私有备份。`);
    } catch (error) { status(`${error.message}\n请检查原因并重新导出快照后重试。`); }
  });

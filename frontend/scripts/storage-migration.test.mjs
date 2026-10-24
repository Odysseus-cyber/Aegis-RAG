import { beforeEach, expect, test, vi } from "vitest";
import { migrateStorage, snapshotStorage, TARGET_KEYS } from "../public/storage-migration.mjs";

const origin = "http://127.0.0.1:15173";
const conversations = JSON.stringify([{ id: "session-1", docFilter: ["fixture"], messages: [
  { id: "local-answer", serverMessageId: "server-answer", feedbackRating: 1, content: "answer" },
] }]);
const sourceKeys = { sourceConversationKey: "source_sessions", sourceActiveKey: "source_selection" };
let storage;
beforeEach(() => {
  const values = new Map();
  storage = { getItem: (key) => values.get(key) ?? null,
    setItem: (key, value) => values.set(key, value), removeItem: (key) => values.delete(key) };
});
function populate() {
  storage.setItem(sourceKeys.sourceConversationKey, conversations);
  storage.setItem(sourceKeys.sourceActiveKey, JSON.stringify("session-1"));
}
function snapshot() { return snapshotStorage({ storage, origin, ...sourceKeys }); }
function migrate(options = {}) {
  return migrateStorage({ storage, origin, snapshot: snapshot(), exportBackup: async () => true, ...options });
}

test("empty storage and repeated migration are idempotent", async () => {
  expect((await migrate()).status).toBe("unchanged");
  populate();
  await migrate();
  expect((await migrate()).status).toBe("unchanged");
});

test("exports before writing and preserves message, feedback and active IDs byte for byte", async () => {
  populate();
  const exportBackup = vi.fn(async (backup) => {
    expect(storage.getItem(TARGET_KEYS.conversations)).toBeNull();
    expect(backup.source.conversations).toBe(conversations);
    return true;
  });
  expect((await migrate({ exportBackup })).migratedKeys).toBe(2);
  expect(exportBackup).toHaveBeenCalledOnce();
  expect(storage.getItem(TARGET_KEYS.conversations)).toBe(conversations);
  expect(storage.getItem(TARGET_KEYS.active)).toBe(JSON.stringify("session-1"));
  expect(storage.getItem(sourceKeys.sourceConversationKey)).toBeNull();
});

test("target conflicts preserve both copies", async () => {
  populate(); storage.setItem(TARGET_KEYS.conversations, "[]");
  await expect(migrate()).rejects.toThrow("conflict");
  expect(storage.getItem(sourceKeys.sourceConversationKey)).toBe(conversations);
  expect(storage.getItem(TARGET_KEYS.conversations)).toBe("[]");
});

test("backup failure never writes or removes data", async () => {
  populate();
  await expect(migrate({ exportBackup: async () => false })).rejects.toThrow("backup");
  expect(storage.getItem(TARGET_KEYS.conversations)).toBeNull();
  expect(storage.getItem(sourceKeys.sourceConversationKey)).toBe(conversations);
});

test("interrupted destination writes retain source and revert earlier target writes", async () => {
  populate();
  const setItem = storage.setItem;
  storage.setItem = (key, value) => { if (key === TARGET_KEYS.active) throw new Error("Quota exceeded"); setItem(key, value); };
  await expect(migrate()).rejects.toThrow("Quota exceeded");
  expect(storage.getItem(TARGET_KEYS.conversations)).toBeNull();
  expect(storage.getItem(sourceKeys.sourceConversationKey)).toBe(conversations);
});

test("retry finishes migration after interruption during source removal", async () => {
  populate(); const removeItem = storage.removeItem;
  storage.removeItem = (key) => { if (key === sourceKeys.sourceActiveKey) throw new Error("Interrupted"); removeItem(key); };
  await expect(migrate()).rejects.toThrow("Interrupted");
  expect(storage.getItem(TARGET_KEYS.conversations)).toBe(conversations);
  storage.removeItem = removeItem;
  expect((await migrate()).status).toBe("migrated");
  expect(storage.getItem(TARGET_KEYS.active)).toBe(JSON.stringify("session-1"));
});

test("invalid active references and wrong origin are rejected", async () => {
  populate(); const saved = snapshot();
  await expect(migrate({ snapshot: saved, origin: "http://localhost:5173" })).rejects.toThrow("origin");
  storage.setItem(sourceKeys.sourceActiveKey, '"missing"');
  expect(snapshot).toThrow("active conversation");
});

test("concurrent changes during backup abort migration", async () => {
  populate();
  await expect(migrate({ exportBackup: async () => { storage.setItem(sourceKeys.sourceActiveKey, "null"); return true; } }))
    .rejects.toThrow("during backup");
  expect(storage.getItem(TARGET_KEYS.conversations)).toBeNull();
});

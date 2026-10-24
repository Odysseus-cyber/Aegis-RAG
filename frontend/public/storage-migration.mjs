/** One-time migration utility. Source keys are supplied by the operator. */
export const TARGET_KEYS = Object.freeze({
  conversations: "aegis_rag_conversations",
  active: "aegis_rag_active_conversation",
});

function validate(conversationsRaw, activeRaw) {
  const conversations = conversationsRaw === null ? [] : JSON.parse(conversationsRaw);
  const active = activeRaw === null ? null : JSON.parse(activeRaw);
  if (!Array.isArray(conversations)
    || conversations.some((item) => !item || typeof item.id !== "string" || !Array.isArray(item.messages))
    || new Set(conversations.map((item) => item.id)).size !== conversations.length
    || (active !== null && (typeof active !== "string" || !conversations.some((item) => item.id === active)))) {
    throw new Error("Invalid conversation data or active conversation reference; no data changed.");
  }
}

export function snapshotStorage({ storage, origin, sourceConversationKey, sourceActiveKey }) {
  const sourceKeys = { conversations: sourceConversationKey, active: sourceActiveKey };
  if (!origin || Object.values(sourceKeys).some((key) => typeof key !== "string" || !key)
    || new Set([...Object.values(sourceKeys), ...Object.values(TARGET_KEYS)]).size !== 4) {
    throw new Error("Supply the browser origin and two distinct source keys outside the target namespace.");
  }
  const source = Object.fromEntries(Object.entries(sourceKeys).map(([field, key]) => [field, storage.getItem(key)]));
  const target = Object.fromEntries(Object.entries(TARGET_KEYS).map(([field, key]) => [field, storage.getItem(key)]));
  validate(source.conversations ?? target.conversations, source.active ?? target.active);
  return { format: 1, origin, capturedAt: new Date().toISOString(), sourceKeys, source, target };
}

/** exportBackup must persist and read back the snapshot, then resolve true. */
export async function migrateStorage({ storage, origin, snapshot, exportBackup }) {
  if (snapshot.format !== 1 || snapshot.origin !== origin) throw new Error("Snapshot origin mismatch.");
  const fresh = snapshotStorage({ storage, origin, sourceConversationKey: snapshot.sourceKeys.conversations,
    sourceActiveKey: snapshot.sourceKeys.active });
  for (const field of Object.keys(TARGET_KEYS)) {
    if (fresh.source[field] !== snapshot.source[field] || fresh.target[field] !== snapshot.target[field]) {
      throw new Error("Storage changed after export; capture a new snapshot.");
    }
    if (fresh.source[field] !== null && fresh.target[field] !== null && fresh.source[field] !== fresh.target[field]) {
      throw new Error("Target conflict; both copies were preserved.");
    }
  }
  const fields = Object.keys(TARGET_KEYS).filter((field) => fresh.source[field] !== null);
  if (!fields.length) return { status: "unchanged", migratedKeys: 0 };
  if (typeof exportBackup !== "function" || await exportBackup(snapshot) !== true) {
    throw new Error("A verified external backup is required before migration.");
  }
  // Recheck after the asynchronous backup; the old app must not be writing concurrently.
  for (const field of Object.keys(TARGET_KEYS)) {
    if (storage.getItem(snapshot.sourceKeys[field]) !== snapshot.source[field]
      || storage.getItem(TARGET_KEYS[field]) !== snapshot.target[field]) {
      throw new Error("Storage changed during backup; no migration performed.");
    }
  }
  try {
    for (const field of fields) storage.setItem(TARGET_KEYS[field], snapshot.source[field]);
    for (const field of fields) {
      if (storage.getItem(TARGET_KEYS[field]) !== snapshot.source[field]) throw new Error("Target verification failed.");
    }
  } catch (error) {
    // Source keys are untouched until every destination has been verified.
    for (const field of fields) {
      try {
        if (snapshot.target[field] === null) storage.removeItem(TARGET_KEYS[field]);
        else storage.setItem(TARGET_KEYS[field], snapshot.target[field]);
      } catch { /* A retry detects conflicting partial data; the backup remains available. */ }
    }
    throw error;
  }
  for (const field of fields) {
    storage.removeItem(snapshot.sourceKeys[field]);
    if (storage.getItem(snapshot.sourceKeys[field]) !== null) {
      throw new Error("Source removal failed; verified target and backup are available. Retry after checking storage access.");
    }
  }
  return { status: "migrated", migratedKeys: fields.length };
}

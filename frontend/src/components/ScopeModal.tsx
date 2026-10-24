import { useEffect, useState } from "react";
import { listDocuments } from "../lib/api";
import type { DocumentScope } from "../types";

interface ScopeModalProps {
  onStart: (scope: DocumentScope) => void;
}

export function ScopeModal({ onStart }: ScopeModalProps) {
  const [documents, setDocuments] = useState<string[]>([]);
  const [mode, setMode] = useState<"all" | "select">("all");
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [loading, setLoading] = useState(true);

  const [error, setError] = useState<string | null>(null);
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    let active = true;
    setLoading(true);
    setError(null);
    listDocuments()
      .then((docs) => { if (active) setDocuments(docs); })
      .catch((err: Error) => { if (active) setError(err.message); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [attempt]);

  function toggle(doc: string) {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(doc)) { next.delete(doc); } else { next.add(doc); }
      return next;
    });
  }

  function handleStart() {
    const scope: DocumentScope = mode === "all" ? null : Array.from(selected);
    onStart(scope);
  }

  const canStart = !loading && !error && documents.length > 0 && (mode === "all" || selected.size > 0);

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4">
      <div className="w-full max-w-md rounded-xl bg-white p-6 shadow-xl">
        <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-blue-700">Aegis-RAG</p>
        <h2 className="mb-1 text-lg font-semibold text-gray-900">
          Which documents should I search?
        </h2>
        <p className="mb-4 text-sm text-gray-500">
          This scope applies to the entire conversation.
        </p>

        <div className="mb-4 space-y-2">
          <label className="flex cursor-pointer items-center gap-3 rounded-lg border p-3 hover:bg-gray-50">
            <input
              type="radio"
              name="scope"
              checked={mode === "all"}
              onChange={() => setMode("all")}
              className="h-4 w-4 min-w-[1rem] accent-blue-600"
            />
            <div>
              <p className="font-medium text-gray-800">All documents</p>
              <p className="text-xs text-gray-500">Search across everything ingested</p>
            </div>
          </label>

          <label className="flex cursor-pointer items-center gap-3 rounded-lg border p-3 hover:bg-gray-50">
            <input
              type="radio"
              name="scope"
              checked={mode === "select"}
              onChange={() => setMode("select")}
              className="h-4 w-4 min-w-[1rem] accent-blue-600"
            />
            <div>
              <p className="font-medium text-gray-800">Select documents</p>
              <p className="text-xs text-gray-500">Restrict search to specific documents</p>
            </div>
          </label>
        </div>

        {error && <div role="alert" className="mb-3 text-sm text-red-700">
          Documents could not be loaded: {error}
          <button className="ml-2 underline" onClick={() => setAttempt((value) => value + 1)}>Retry</button>
        </div>}
        {!loading && !error && documents.length === 0 && <p className="mb-3 text-sm text-gray-600">No documents ingested yet. Add a PDF and run the ingestion command.</p>}
        {loading && <p className="mb-3 text-sm text-gray-500">Loading documents…</p>}
        {mode === "select" && (
          <div className="mb-4 max-h-48 overflow-y-auto rounded-lg border p-2">
            {loading ? (
              <p className="p-2 text-sm text-gray-400">Loading documents…</p>
            ) : documents.length === 0 ? (
              <p className="p-2 text-sm text-gray-400">No documents ingested yet.</p>
            ) : (
              documents.map((doc) => (
                <label
                  key={doc}
                  className="flex cursor-pointer items-center gap-3 rounded p-2 hover:bg-gray-50"
                >
                  <input
                    type="checkbox"
                    checked={selected.has(doc)}
                    onChange={() => toggle(doc)}
                    className="h-4 w-4 min-w-[1rem] accent-blue-600"
                  />
                  <span className="truncate text-sm text-gray-700">{doc}</span>
                </label>
              ))
            )}
          </div>
        )}

        <button
          onClick={handleStart}
          disabled={!canStart}
          className="min-h-[44px] w-full rounded-lg bg-blue-600 px-4 py-2 text-sm font-semibold text-white
                     hover:bg-blue-700 disabled:cursor-not-allowed disabled:opacity-40"
        >
          Start
        </button>
      </div>
    </div>
  );
}

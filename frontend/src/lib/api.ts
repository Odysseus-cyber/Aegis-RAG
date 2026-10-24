import type { Citation, DocumentScope, FeedbackRating } from "../types";

const BASE = "/api";

export interface StreamHandlers {
  onMessageId: (messageId: string) => void;
  onCitations: (citations: Citation[]) => void;
  onToken: (token: string) => void;
  onDone: () => void;
  onError: (err: Error) => void;
}

export interface HistoryMessage {
  role: "user" | "assistant";
  content: string;
}

async function responseError(response: Response): Promise<Error> {
  const body = await response.json().catch(() => null);
  return new Error(typeof body?.detail === "string" ? body.detail : `HTTP ${response.status}`);
}

/** Consume a complete SSE response, including failures after headers were sent. */
export function streamChat(
  conversationId: string,
  history: HistoryMessage[],
  message: string,
  docFilter: DocumentScope,
  handlers: StreamHandlers
): AbortController {
  const controller = new AbortController();
  void (async () => {
    let reader: ReadableStreamDefaultReader<Uint8Array> | undefined;
    try {
      const response = await fetch(`${BASE}/chat`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ conversation_id: conversationId, history, message, doc_filter: docFilter }),
        signal: controller.signal,
      });
      if (!response.ok) throw await responseError(response);
      if (!response.body) throw new Error("The server returned no response stream.");
      const messageId = response.headers.get("X-Message-Id");
      if (!messageId) throw new Error("The server returned no message ID.");
      handlers.onMessageId(messageId);
      reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      while (true) {
        const { value, done } = await reader.read();
        buffer += done ? decoder.decode() : decoder.decode(value, { stream: true });
        // Normalize CRLF only once both characters have arrived.
        buffer = buffer.replace(/\r\n/g, "\n");
        let boundary: number;
        while ((boundary = buffer.indexOf("\n\n")) !== -1) {
          const part = buffer.slice(0, boundary);
          buffer = buffer.slice(boundary + 2);
          const lines = part.split("\n");
          const eventType = lines.find((line) => line.startsWith("event:"))?.slice(6).trim() ?? "message";
          const raw = lines.filter((line) => line.startsWith("data:")).map((line) => line.slice(5).trimStart()).join("\n");
          if (!raw) continue;
          const data = JSON.parse(raw);
          if (eventType === "error") throw new Error(data.message ?? "The request failed.");
          if (eventType === "done") {
            handlers.onDone();
            return;
          }
          if (eventType === "citations") handlers.onCitations(data as Citation[]);
          else if (eventType === "message" && typeof data.token === "string") handlers.onToken(data.token);
        }
        if (done) throw new Error("The response ended before completion. Please retry.");
      }
    } catch (err) {
      handlers.onError(controller.signal.aborted
        ? new Error("Response cancelled.")
        : err instanceof Error ? err : new Error(String(err)));
    } finally {
      if (reader) {
        await reader.cancel().catch(() => undefined);
        reader.releaseLock();
      }
    }
  })();
  return controller;
}

export async function submitFeedback(messageId: string, rating: FeedbackRating, comment?: string): Promise<void> {
  const response = await fetch(`${BASE}/feedback`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ message_id: messageId, rating, comment }),
  });
  if (!response.ok) throw await responseError(response);
}

export async function listDocuments(): Promise<string[]> {
  const response = await fetch(`${BASE}/admin/documents`);
  if (!response.ok) throw await responseError(response);
  const data: { documents: string[] } = await response.json();
  return data.documents;
}

export interface AppVersion {
  name: string;
  commit_sha: string;
  build_time: string;
  actions_url: string | null;
}

export async function getVersion(signal: AbortSignal): Promise<AppVersion> {
  const response = await fetch(`${BASE}/version`, { signal });
  if (!response.ok) throw await responseError(response);
  const data: AppVersion = await response.json();
  if (typeof data.commit_sha !== "string") throw new Error("Invalid version");
  return data;
}

import { describe, it, expect, vi } from "vitest";
import { waitFor } from "@testing-library/react";
import { streamChat, submitFeedback, listDocuments } from "./api";

function handlers() {
  return { onMessageId: vi.fn(), onCitations: vi.fn(), onToken: vi.fn(), onDone: vi.fn(), onError: vi.fn() };
}

function response(text: string) {
  const bytes = new TextEncoder().encode(text);
  return new Response(new ReadableStream({
    start(controller) {
      // Split even UTF-8 sequences and event delimiters across network chunks.
      for (const byte of bytes) controller.enqueue(new Uint8Array([byte]));
      controller.close();
    },
  }), { headers: { "X-Message-Id": "server-id" } });
}

describe("streamChat", () => {
  it("decodes split SSE frames and exposes the server message ID", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(response(
      'event: citations\r\ndata: []\r\n\r\ndata: {"token":"你好"}\n\ndata: {"token":" world"}\n\nevent: done\ndata: {}\n\n'
    )));
    const h = handlers();
    streamChat("conv", [], "hi", null, h);
    await waitFor(() => expect(h.onDone).toHaveBeenCalledOnce());
    expect(h.onMessageId).toHaveBeenCalledWith("server-id");
    expect(h.onToken.mock.calls.flat().join("")).toBe("你好 world");
    expect(h.onError).not.toHaveBeenCalled();
  });

  it.each([
    ['event: error\ndata: {"message":"Ollama unavailable"}\n\n', "Ollama unavailable"],
    ['data: {"token":"Partial"}\n\n', "before completion"],
    ['data: not-json\n\n', "JSON"],
  ])("reports a failed or incomplete stream", async (body, error) => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(response(body)));
    const h = handlers();
    streamChat("conv", [], "hi", null, h);
    await waitFor(() => expect(h.onError).toHaveBeenCalledOnce());
    expect(h.onError.mock.calls[0][0].message).toContain(error);
    expect(h.onDone).not.toHaveBeenCalled();
  });

  it("handles a reader failure", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(new ReadableStream({
      start(controller) { controller.error(new Error("connection lost")); },
    }), { headers: { "X-Message-Id": "server-id" } })));
    const h = handlers();
    streamChat("conv", [], "hi", null, h);
    await waitFor(() => expect(h.onError).toHaveBeenCalledOnce());
    expect(h.onDone).not.toHaveBeenCalled();
  });

  it("reports cancellation before response headers", async () => {
    vi.stubGlobal("fetch", vi.fn((_url, init: RequestInit) => new Promise((_resolve, reject) => {
      init.signal?.addEventListener("abort", () => reject(new DOMException("Aborted", "AbortError")));
    })));
    const h = handlers();
    streamChat("conv", [], "hi", null, h).abort();
    await waitFor(() => expect(h.onError).toHaveBeenCalledOnce());
    expect(h.onError.mock.calls[0][0].message).toContain("cancelled");
  });
});

it("does not silently accept HTTP errors for feedback or document listing", async () => {
  vi.stubGlobal("fetch", vi.fn().mockImplementation(() => Promise.resolve(new Response('{"detail":"Unavailable"}', { status: 503 }))));
  await expect(submitFeedback("id", 1)).rejects.toThrow("Unavailable");
  await expect(listDocuments()).rejects.toThrow("Unavailable");
});

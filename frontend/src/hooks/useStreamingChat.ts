import { useCallback, useEffect, useRef } from "react";
import { streamChat } from "../lib/api";
import type { Citation, DocumentScope, Message } from "../types";

interface UseStreamingChatOptions {
  conversationId: string;
  docFilter: DocumentScope;
  history: Message[];
  onAssistantStart: (messageId: string) => void;
  onMessageId: (messageId: string, serverMessageId: string) => void;
  onToken: (messageId: string, token: string) => void;
  onCitations: (messageId: string, citations: Citation[]) => void;
  onDone: (messageId: string) => void;
  onError: (messageId: string, err: Error) => void;
}

export function useStreamingChat(opts: UseStreamingChatOptions) {
  const abortRef = useRef<AbortController | null>(null);
  const send = useCallback((userMessage: string) => {
    abortRef.current?.abort();
    const messageId = crypto.randomUUID();
    opts.onAssistantStart(messageId);
    const history = opts.history
      .filter((message) => !message.isStreaming && !message.error)
      .map((message) => ({ role: message.role, content: message.content }));
    abortRef.current = streamChat(opts.conversationId, history, userMessage, opts.docFilter, {
      onMessageId: (serverId) => opts.onMessageId(messageId, serverId),
      onCitations: (citations) => opts.onCitations(messageId, citations),
      onToken: (token) => opts.onToken(messageId, token),
      onDone: () => opts.onDone(messageId),
      onError: (err) => opts.onError(messageId, err),
    });
  }, [opts]);

  const cancel = useCallback(() => {
    abortRef.current?.abort();
    abortRef.current = null;
  }, []);

  useEffect(() => cancel, [opts.conversationId, cancel]);
  return { send, cancel };
}

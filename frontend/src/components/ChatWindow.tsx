import { useCallback } from "react";
import { MessageList } from "./MessageList";
import { MessageInput } from "./MessageInput";
import { DocumentBadge } from "./DocumentBadge";
import { useStreamingChat } from "../hooks/useStreamingChat";
import type { Citation, Conversation, FeedbackRating, Message, MessagePatch } from "../types";

interface ChatWindowProps {
  conversation: Conversation;
  onNewChat?: () => void;
  onAddMessage: (conversationId: string, message: Message) => void;
  onUpdateMessage: (conversationId: string, messageId: string, patch: MessagePatch) => void;
  onFeedback: (conversationId: string, messageId: string, rating: FeedbackRating) => void;
}

export function ChatWindow({
  conversation,
  onAddMessage,
  onUpdateMessage,
  onFeedback,
  onNewChat,
}: ChatWindowProps) {
  const handleAssistantStart = useCallback(
    (messageId: string) => {
      onAddMessage(conversation.id, {
        id: messageId,
        role: "assistant",
        content: "",
        isStreaming: true,
      });
    },
    [conversation.id, onAddMessage]
  );

  const handleToken = useCallback(
    (messageId: string, token: string) => {
      onUpdateMessage(conversation.id, messageId, (message) => ({
        content: message.content + token,
      }));
    },
    [conversation.id, onUpdateMessage]
  );

  const handleCitations = useCallback(
    (messageId: string, citations: Citation[]) => {
      onUpdateMessage(conversation.id, messageId, { citations });
    },
    [conversation.id, onUpdateMessage]
  );

  const handleDone = useCallback(
    (messageId: string) => {
      onUpdateMessage(conversation.id, messageId, { isStreaming: false });
    },
    [conversation.id, onUpdateMessage]
  );

  const { send, cancel } = useStreamingChat({
    conversationId: conversation.id,
    docFilter: conversation.docFilter,
    history: conversation.messages,
    onAssistantStart: handleAssistantStart,
    onMessageId: (messageId, serverMessageId) => onUpdateMessage(conversation.id, messageId, { serverMessageId }),
    onToken: handleToken,
    onCitations: handleCitations,
    onDone: handleDone,
    onError: (messageId, err) => onUpdateMessage(conversation.id, messageId, { isStreaming: false, error: err.message }),
  });

  function handleSend(text: string) {
    onAddMessage(conversation.id, {
      id: crypto.randomUUID(),
      role: "user",
      content: text,
    });
    send(text);
  }

  const isStreaming = conversation.messages.some((m) => m.isStreaming);

  return (
    <div className="flex h-full flex-col">
      {/* Header */}
      <header className="flex items-center gap-3 border-b border-gray-200 bg-white px-4 py-2">
        <h1 className="shrink-0 text-sm font-semibold text-gray-800">Aegis-RAG</h1>
        <div className="flex min-w-0 flex-1 items-center justify-end gap-2">
          <DocumentBadge docFilter={conversation.docFilter} />
          {onNewChat && (
            <button
              onClick={onNewChat}
              className="min-h-[44px] shrink-0 rounded-lg bg-white px-3 py-2 text-xs font-medium text-gray-600 ring-1 ring-gray-200 hover:bg-gray-50"
            >
              New chat
            </button>
          )}
        </div>
      </header>

      {/* Messages */}
      <MessageList
        conversationId={conversation.id}
        messages={conversation.messages}
        onFeedback={(messageId, rating) => onFeedback(conversation.id, messageId, rating)}
      />

      {/* Input */}
      {isStreaming && <button onClick={cancel} className="p-2 text-sm text-gray-600">Stop response</button>}
      <MessageInput onSend={handleSend} disabled={isStreaming} />
    </div>
  );
}

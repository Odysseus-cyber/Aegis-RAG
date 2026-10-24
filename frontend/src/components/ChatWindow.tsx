import { useCallback } from "react";
import { MessageList } from "./MessageList";
import { MessageInput } from "./MessageInput";
import { DocumentBadge } from "./DocumentBadge";
import { useStreamingChat } from "../hooks/useStreamingChat";
import type { Citation, Conversation, FeedbackRating, Message, MessagePatch } from "../types";

interface ChatWindowProps {
  conversation: Conversation;
  onAddMessage: (conversationId: string, message: Message) => void;
  onUpdateMessage: (conversationId: string, messageId: string, patch: MessagePatch) => void;
  onFeedback: (conversationId: string, messageId: string, rating: FeedbackRating) => void;
}

export function ChatWindow({
  conversation,
  onAddMessage,
  onUpdateMessage,
  onFeedback,
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
      <div className="flex items-center justify-between border-b border-gray-200 bg-white px-4 py-3">
        <h1 className="text-sm font-semibold text-gray-800">Aegis-RAG</h1>
        <DocumentBadge docFilter={conversation.docFilter} />
      </div>

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

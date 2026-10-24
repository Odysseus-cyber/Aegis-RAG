import { useState } from "react";
import { VersionInfo } from "./components/VersionInfo";
import { ScopeModal } from "./components/ScopeModal";
import { ChatWindow } from "./components/ChatWindow";
import { useConversation } from "./hooks/useConversation";
import type { DocumentScope } from "./types";

export default function App() {
  const {
    active,
    startConversation,
    addMessage,
    updateMessage,
    setFeedback,
  } = useConversation();

  const [showScopeModal, setShowScopeModal] = useState(!active);

  function handleStart(scope: DocumentScope) {
    startConversation(scope);
    setShowScopeModal(false);
  }

  function handleNewConversation() {
    setShowScopeModal(true);
  }

  return (
    <div className="flex h-dvh flex-col bg-gray-100">
      {showScopeModal && <ScopeModal onStart={handleStart} />}

      <div className="min-h-0 flex-1">
        {active && (
          <ChatWindow
            conversation={active}
            onAddMessage={addMessage}
            onUpdateMessage={updateMessage}
            onFeedback={setFeedback}
            onNewChat={showScopeModal ? undefined : handleNewConversation}
          />
        )}
      </div>
      <VersionInfo />
    </div>
  );
}

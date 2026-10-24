import { act, fireEvent, render, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import { ChatWindow } from "./ChatWindow";
import { useConversation } from "../hooks/useConversation";
import type { StreamHandlers } from "../lib/api";
import { streamChat } from "../lib/api";

vi.mock("../lib/api", () => ({ streamChat: vi.fn(), submitFeedback: vi.fn() }));

function Harness() {
  const chat = useConversation();
  return chat.active ? <ChatWindow conversation={chat.active} onAddMessage={chat.addMessage} onUpdateMessage={chat.updateMessage} onFeedback={chat.setFeedback} /> : null;
}
function seed(streaming = false) {
  localStorage.setItem("aegis_rag_active_conversation", JSON.stringify("conv"));
  localStorage.setItem("aegis_rag_conversations", JSON.stringify([{
    id: "conv", docFilter: null, createdAt: "2026-01-01",
    messages: streaming ? [{ id: "old", role: "assistant", content: "Partial", isStreaming: true }] : [],
  }]));
}
function send() {
  fireEvent.change(screen.getByRole("textbox"), { target: { value: "Question" } });
  fireEvent.click(screen.getByRole("button", { name: /send/i }));
}

it("accumulates tokens from one stream across re-renders and releases input on error", () => {
  seed();
  let handlers!: StreamHandlers;
  vi.mocked(streamChat).mockImplementation((_id, _history, _message, _scope, h) => {
    handlers = h;
    return new AbortController();
  });
  render(<Harness />);
  send();
  act(() => { handlers.onMessageId("real-id"); handlers.onToken("First "); });
  act(() => handlers.onToken("second "));
  act(() => { handlers.onToken("third"); handlers.onError(new Error("Model offline")); });
  expect(screen.getByText("First second third")).toBeTruthy();
  expect(screen.getByRole("alert").textContent).toContain("Model offline");
  expect((screen.getByRole("textbox") as HTMLTextAreaElement).disabled).toBe(false);
  expect(screen.queryByRole("button", { name: "Thumbs up" })).toBeNull();
});

it("uses the backend ID for feedback on completed answers", async () => {
  seed();
  let handlers!: StreamHandlers;
  vi.mocked(streamChat).mockImplementation((_id, _history, _message, _scope, h) => {
    handlers = h;
    return new AbortController();
  });
  render(<Harness />);
  send();
  act(() => { handlers.onMessageId("real-id"); handlers.onToken("Answer"); handlers.onDone(); });
  await act(async () => fireEvent.click(screen.getByRole("button", { name: "Thumbs up" })));
  const { submitFeedback } = await import("../lib/api");
  expect(submitFeedback).toHaveBeenCalledWith("real-id", 1);
});

it("cancels the pending request on unmount", () => {
  seed();
  const controller = new AbortController();
  vi.mocked(streamChat).mockReturnValue(controller);
  const view = render(<Harness />);
  send();
  view.unmount();
  expect(controller.signal.aborted).toBe(true);
});

it("restores interrupted localStorage messages without locking the input", () => {
  seed(true);
  render(<Harness />);
  expect(screen.getByRole("alert").textContent).toContain("interrupted");
  expect((screen.getByRole("textbox") as HTMLTextAreaElement).disabled).toBe(false);
});


it("groups document scope and the new chat action in the chat header", () => {
  const onNewChat = vi.fn();
  render(<ChatWindow
    conversation={{ id: "conv", docFilter: ["A long selected policy document.pdf"], messages: [], createdAt: "2026-01-01" }}
    onAddMessage={vi.fn()}
    onUpdateMessage={vi.fn()}
    onFeedback={vi.fn()}
    onNewChat={onNewChat}
  />);
  const button = screen.getByRole("button", { name: "New chat" });
  const badge = screen.getByText("A long selected policy document.pdf");
  expect(button.closest("header")).toBe(badge.closest("header"));
  expect(badge.getAttribute("title")).toBe("A long selected policy document.pdf");
  fireEvent.click(button);
  expect(onNewChat).toHaveBeenCalledOnce();
});

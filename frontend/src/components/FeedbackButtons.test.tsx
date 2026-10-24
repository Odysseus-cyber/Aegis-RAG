import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import { FeedbackButtons } from "./FeedbackButtons";
import { submitFeedback } from "../lib/api";

vi.mock("../lib/api", () => ({ submitFeedback: vi.fn() }));

it("keeps failed feedback retryable and confirms only a successful request", async () => {
  vi.mocked(submitFeedback).mockRejectedValueOnce(new Error("offline")).mockResolvedValueOnce();
  const onRated = vi.fn();
  render(<FeedbackButtons messageId="server-id" onRated={onRated} />);
  const button = screen.getByRole("button", { name: "Thumbs up" });
  fireEvent.click(button);
  await screen.findByRole("alert");
  expect(onRated).not.toHaveBeenCalled();
  expect((button as HTMLButtonElement).disabled).toBe(false);
  fireEvent.click(button);
  await waitFor(() => expect(onRated).toHaveBeenCalledWith(1));
  expect(screen.queryByRole("alert")).toBeNull();
});

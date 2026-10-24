import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import { ScopeModal } from "./ScopeModal";
import { listDocuments } from "../lib/api";

vi.mock("../lib/api", () => ({ listDocuments: vi.fn() }));

it("distinguishes empty documents from errors and retries failures", async () => {
  vi.mocked(listDocuments).mockRejectedValueOnce(new Error("backend unavailable")).mockResolvedValueOnce([]);
  render(<ScopeModal onStart={vi.fn()} />);
  expect((await screen.findByRole("alert")).textContent).toContain("backend unavailable");
  fireEvent.click(screen.getByRole("button", { name: "Retry" }));
  await screen.findByText(/No documents ingested yet. Add/);
  expect(screen.queryByRole("alert")).toBeNull();
  expect((screen.getByRole("button", { name: "Start" }) as HTMLButtonElement).disabled).toBe(true);
});

it("passes the selected document scope to the new conversation", async () => {
  vi.mocked(listDocuments).mockResolvedValueOnce(["Sample"]);
  const onStart = vi.fn();
  render(<ScopeModal onStart={onStart} />);
  await waitFor(() => expect((screen.getByRole("button", { name: "Start" }) as HTMLButtonElement).disabled).toBe(false));
  fireEvent.click(screen.getByLabelText(/Select documents/));
  fireEvent.click(screen.getByLabelText("Sample"));
  fireEvent.click(screen.getByRole("button", { name: "Start" }));
  expect(onStart).toHaveBeenCalledWith(["Sample"]);
});

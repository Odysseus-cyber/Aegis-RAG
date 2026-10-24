import { render, screen, waitFor } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import { VersionInfo } from "./VersionInfo";

it("shows the deployed commit and its Actions run", async () => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify({
    name: "Aegis-RAG", commit_sha: "1234567890abcdef", build_time: "2026-10-24T00:00:00Z",
    actions_url: "https://github.com/Odysseus-cyber/Aegis-RAG/actions/runs/123",
  }))));
  render(<VersionInfo />);
  const link = await screen.findByRole("link", { name: "12345678" });
  expect(link.getAttribute("href")).toBe("https://github.com/Odysseus-cyber/Aegis-RAG/actions/runs/123");
  expect(fetch).toHaveBeenCalledWith("/api/version", expect.objectContaining({ signal: expect.any(AbortSignal) }));
});

it("keeps the application usable when version metadata is unavailable", async () => {
  const fetchMock = vi.fn().mockRejectedValue(new Error("Offline"));
  vi.stubGlobal("fetch", fetchMock);
  render(<VersionInfo />);
  await waitFor(() => expect(fetchMock).toHaveBeenCalled());
  expect(screen.getByText("Aegis-RAG · version unavailable")).toBeTruthy();
  expect(screen.queryByRole("alert")).toBeNull();
});

it.each(["unknown", "development"])("shows %s builds without a run link", async (commitSha) => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify({
    name: "Aegis-RAG", commit_sha: commitSha, build_time: "", actions_url: null,
  }))));
  render(<VersionInfo />);
  expect(await screen.findByText("local")).toBeTruthy();
  expect(screen.queryByRole("link")).toBeNull();
});

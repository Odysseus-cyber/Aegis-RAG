import { useEffect, useState } from "react";

import { getVersion, type AppVersion } from "../lib/api";

export function VersionInfo() {
  const [version, setVersion] = useState<AppVersion | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    void getVersion(controller.signal)
      .then((data) => {
        if (!controller.signal.aborted) setVersion(data);
      })
      .catch(() => undefined);
    return () => controller.abort();
  }, []);

  const label = version?.commit_sha && !["unknown", "development"].includes(version.commit_sha)
    ? version.commit_sha.slice(0, 8)
    : "local";
  const actionsUrl = version?.actions_url?.startsWith("https://github.com/")
    ? version.actions_url
    : null;

  return (
    <footer className="border-t border-gray-200 bg-white px-4 py-1 text-center text-xs text-gray-500">
      Aegis-RAG · {version ? (
        actionsUrl ? <a href={actionsUrl} target="_blank" rel="noreferrer" title={`Built ${version.build_time}`} className="underline">{label}</a>
          : <span title={version.build_time ? `Built ${version.build_time}` : undefined}>{label}</span>
      ) : "version unavailable"}
    </footer>
  );
}

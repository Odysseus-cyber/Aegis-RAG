import type { DocumentScope } from "../types";

interface DocumentBadgeProps {
  docFilter: DocumentScope;
}

export function DocumentBadge({ docFilter }: DocumentBadgeProps) {
  const label =
    docFilter === null
      ? "All documents"
      : docFilter.length === 1
        ? docFilter[0]
        : `${docFilter.length} documents`;

  return (
    <span title={label} className="min-w-0 max-w-full truncate rounded-full bg-blue-100 px-3 py-1 text-xs font-medium text-blue-800">
      {label}
    </span>
  );
}

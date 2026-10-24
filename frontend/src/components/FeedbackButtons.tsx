import { useState } from "react";
import { ThumbsUp, ThumbsDown } from "lucide-react";
import { clsx } from "clsx";
import { submitFeedback } from "../lib/api";
import type { FeedbackRating } from "../types";

interface FeedbackButtonsProps {
  messageId: string;
  currentRating?: FeedbackRating;
  onRated: (rating: FeedbackRating) => void;
}

export function FeedbackButtons({
  messageId,
  currentRating,
  onRated,
}: FeedbackButtonsProps) {
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleClick(rating: FeedbackRating) {
    if (currentRating !== undefined || pending) return;
    setPending(true);
    setError(null);
    try {
      await submitFeedback(messageId, rating);
      onRated(rating);
    } catch {
      setError("Feedback could not be saved. Please retry.");
    } finally {
      setPending(false);
    }
  }

  return (
    <div className="mt-1 flex gap-2">
      <button
        onClick={() => handleClick(1)}
        disabled={currentRating !== undefined || pending}
        aria-label="Thumbs up"
        className={clsx(
          "flex min-h-[44px] min-w-[44px] items-center justify-center rounded-lg p-2 transition-colors",
          currentRating === 1
            ? "bg-green-100 text-green-600"
            : "text-gray-400 hover:bg-gray-100 hover:text-gray-600 disabled:cursor-default"
        )}
      >
        <ThumbsUp className="h-4 w-4" />
      </button>
      <button
        onClick={() => handleClick(-1)}
        disabled={currentRating !== undefined || pending}
        aria-label="Thumbs down"
        className={clsx(
          "flex min-h-[44px] min-w-[44px] items-center justify-center rounded-lg p-2 transition-colors",
          currentRating === -1
            ? "bg-red-100 text-red-600"
            : "text-gray-400 hover:bg-gray-100 hover:text-gray-600 disabled:cursor-default"
        )}
      >
        <ThumbsDown className="h-4 w-4" />
      </button>
      {error && <p role="alert" className="text-sm text-red-700">{error}</p>}
    </div>
  );
}

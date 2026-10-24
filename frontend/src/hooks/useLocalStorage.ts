import { useState, useCallback } from "react";

/**
 * Generic typed localStorage hook.
 * Reads from localStorage on first render; writes on every update.
 */
export function useLocalStorage<T>(
  key: string,
  initialValue: T,
  restore?: (value: T) => T
): [T, (value: T | ((prev: T) => T)) => void] {
  const [storedValue, setStoredValue] = useState<T>(() => {
    try {
      const item = window.localStorage.getItem(key);
      const value = item ? (JSON.parse(item) as T) : initialValue;
      return restore ? restore(value) : value;
    } catch {
      return initialValue;
    }
  });

  const setValue = useCallback(
    (value: T | ((prev: T) => T)) => {
      setStoredValue((prev) => {
        const next = value instanceof Function ? value(prev) : value;
        try {
          window.localStorage.setItem(key, JSON.stringify(next));
        } catch {
          // localStorage full or unavailable — continue in-memory
        }
        return next;
      });
    },
    [key]
  );

  return [storedValue, setValue];
}

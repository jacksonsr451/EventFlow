import { useEffect } from "react";

export function useDocumentTitle(title: string | null | undefined): void {
  useEffect(() => {
    const previous = document.title;
    document.title = title ? `${title} · EventFlow` : "EventFlow";
    return () => {
      document.title = previous;
    };
  }, [title]);
}

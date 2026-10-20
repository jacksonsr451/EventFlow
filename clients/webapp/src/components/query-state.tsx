import { ErrorState } from "@eventflow/ui";
import { presentError } from "../lib/errors";

export function QueryErrorState({
  error,
  onRetry,
  title,
  className,
}: {
  error: unknown;
  onRetry?: () => void;
  title?: string;
  className?: string;
}) {
  const presented = presentError(error);
  return (
    <ErrorState
      status={presented.status}
      title={title ?? presented.title}
      description={presented.description}
      correlationId={presented.correlationId}
      onRetry={onRetry}
      className={className}
    />
  );
}

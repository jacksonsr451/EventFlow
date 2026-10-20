import { ApiProblem } from "@eventflow/api-client";

export interface ErrorPresentation {
  status: number | undefined;
  title: string;
  description: string;
  correlationId: string | undefined;
}

export function presentError(error: unknown): ErrorPresentation {
  if (error instanceof ApiProblem) {
    if (error.status === 401) {
      return {
        status: 401,
        title: "Your session has expired",
        description: "Sign in again to continue where you left off.",
        correlationId: error.correlationId,
      };
    }
    if (error.status === 403) {
      return {
        status: 403,
        title: "You do not have access",
        description:
          "Your workspace role does not allow this view. Ask a workspace administrator if you need access.",
        correlationId: error.correlationId,
      };
    }
    if (error.status === 404) {
      return {
        status: 404,
        title: "This item is not available",
        description:
          "It may have been moved, removed, or you may not have permission to view it.",
        correlationId: error.correlationId,
      };
    }
    return {
      status: error.status,
      title: error.title,
      description: error.detail,
      correlationId: error.correlationId,
    };
  }

  if (error instanceof Error && error.message) {
    return {
      status: undefined,
      title: "Something went wrong",
      description: error.message,
      correlationId: undefined,
    };
  }

  return {
    status: undefined,
    title: "Something went wrong",
    description: "An unexpected error occurred. Try again.",
    correlationId: undefined,
  };
}

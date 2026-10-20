import { ApiProblem } from "@eventflow/api-client";
import { QueryClient } from "@tanstack/react-query";

export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 20_000,
      refetchOnWindowFocus: false,
      retry: (failureCount, error) => {
        if (error instanceof ApiProblem) {
          return error.isRetryable && failureCount < 2;
        }
        return failureCount < 1;
      },
    },
    mutations: {
      retry: false,
    },
  },
});

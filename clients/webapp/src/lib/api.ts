import {
  ApiClient,
  createWorkManagementApi,
} from "@eventflow/api-client";

let csrfToken: string | null = null;

export const apiClient = new ApiClient({
  baseUrl: import.meta.env.VITE_API_BASE_URL ?? "",
  getCsrfToken: () => csrfToken,
});

export const api = createWorkManagementApi(apiClient);

export function setCsrfToken(token: string | null): void {
  csrfToken = token;
}

export function getCsrfToken(): string | null {
  return csrfToken;
}

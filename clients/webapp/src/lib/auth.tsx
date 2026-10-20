import {
  ApiProblem,
  queryKeys,
  type SessionResponse,
} from "@eventflow/api-client";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  createContext,
  useCallback,
  useContext,
  useMemo,
  type ReactNode,
} from "react";
import { Navigate, useLocation, useNavigate } from "react-router-dom";
import { Spinner } from "@eventflow/ui";
import { api, setCsrfToken } from "./api";

export const sessionQueryOptions = {
  queryKey: queryKeys.session,
  queryFn: async (): Promise<SessionResponse> => {
    try {
      const session = await api.getSession();
      setCsrfToken(session.csrf_token);
      return session;
    } catch (error) {
      setCsrfToken(null);
      throw error;
    }
  },
  retry: false,
  staleTime: 60_000,
  refetchOnWindowFocus: false,
} as const;

interface AuthContextValue {
  session: SessionResponse | null;
  status: "loading" | "authenticated" | "unauthenticated";
  isLoading: boolean;
  isAuthenticated: boolean;
  login: () => void;
  logout: () => Promise<void>;
  reloadSession: () => Promise<SessionResponse | null>;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const sessionQuery = useQuery(sessionQueryOptions);
  const session = sessionQuery.data ?? null;

  const login = useCallback(() => {
    window.location.assign("/v1/auth/oidc/login");
  }, []);

  const logout = useCallback(async () => {
    try {
      await api.logout();
    } catch (error) {
      if (!(error instanceof ApiProblem) || error.status !== 401) {
        throw error;
      }
    }
    setCsrfToken(null);
    queryClient.clear();
    navigate("/login?loggedOut=1", { replace: true });
  }, [navigate, queryClient]);

  const reloadSession = useCallback(async () => {
    return queryClient.fetchQuery(sessionQueryOptions);
  }, [queryClient]);

  const status = session
    ? "authenticated"
    : sessionQuery.isPending
      ? "loading"
      : "unauthenticated";

  const value = useMemo<AuthContextValue>(
    () => ({
      session,
      status,
      isLoading: sessionQuery.isPending,
      isAuthenticated: Boolean(session),
      login,
      logout,
      reloadSession,
    }),
    [session, status, sessionQuery.isPending, login, logout, reloadSession],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error("useAuth must be used within an AuthProvider");
  }
  return context;
}

export function RequireAuth({ children }: { children: ReactNode }) {
  const { status } = useAuth();
  const location = useLocation();

  if (status === "loading") {
    return (
      <div className="flex min-h-dvh flex-col items-center justify-center gap-3 bg-background">
        <div className="flex size-12 items-center justify-center rounded-xl bg-primary text-xl font-semibold text-primary-foreground">
          EF
        </div>
        <Spinner label="Checking your session" />
      </div>
    );
  }

  if (status !== "authenticated") {
    return <Navigate to="/login" state={{ from: location }} replace />;
  }

  return children;
}

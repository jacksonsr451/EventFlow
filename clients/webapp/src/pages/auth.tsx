import { ArrowRight, LockKeyhole, ShieldCheck } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import {
  Navigate,
  useLocation,
  useNavigate,
  useSearchParams,
} from "react-router-dom";
import { Alert, Button, Spinner } from "@eventflow/ui";
import { useAuth } from "../lib/auth";
import { presentError } from "../lib/errors";
import { useDocumentTitle } from "../lib/use-document-title";

const RETURN_TO_KEY = "eventflow.returnTo";

function safeReturnPath(value: string | null): string {
  return value?.startsWith("/") && !value.startsWith("//") ? value : "/";
}

export function LoginPage() {
  const { status, login } = useAuth();
  const location = useLocation();
  const [searchParams] = useSearchParams();
  useDocumentTitle("Sign in");

  const from = (
    location.state as { from?: { pathname?: string; search?: string } } | null
  )?.from;
  const intendedPath =
    from?.pathname && from.pathname !== "/login"
      ? `${from.pathname}${from.search ?? ""}`
      : "/";

  if (status === "loading") {
    return (
      <div className="flex min-h-dvh items-center justify-center bg-background">
        <Spinner label="Checking your session" />
      </div>
    );
  }

  if (status === "authenticated") {
    return <Navigate to={safeReturnPath(intendedPath)} replace />;
  }

  const expired = searchParams.get("expired") === "1";
  const loggedOut = searchParams.get("loggedOut") === "1";

  function handleLogin() {
    try {
      sessionStorage.setItem(RETURN_TO_KEY, intendedPath);
    } catch {
      // The post-login destination defaults to the dashboard.
    }
    login();
  }

  return (
    <main className="grid min-h-dvh bg-background lg:grid-cols-[1.1fr_1fr]">
      <section className="relative hidden overflow-hidden bg-primary p-10 text-primary-foreground lg:flex lg:flex-col lg:justify-between">
        <div
          className="absolute inset-0 opacity-20"
          aria-hidden="true"
          style={{
            backgroundImage:
              "radial-gradient(circle at 20% 20%, white 0, transparent 35%), radial-gradient(circle at 80% 80%, white 0, transparent 30%)",
          }}
        />
        <div className="relative">
          <div className="flex items-center gap-3">
            <span className="flex size-10 items-center justify-center rounded-xl bg-white/15 text-sm font-bold">
              EF
            </span>
            <span className="text-lg font-semibold tracking-tight">
              EventFlow
            </span>
          </div>
        </div>
        <div className="relative max-w-xl">
          <p className="mb-4 text-sm font-semibold uppercase tracking-[0.2em] text-primary-foreground/70">
            Work management
          </p>
          <h1 className="text-balance text-4xl font-semibold leading-tight tracking-tight">
            From incoming request to approved delivery, in one place.
          </h1>
          <p className="mt-5 max-w-md text-base leading-relaxed text-primary-foreground/80">
            Triage consultations, review proposals, plan work items, and keep
            delivery boards aligned with your team.
          </p>
          <div className="mt-8 flex flex-wrap gap-5 text-sm text-primary-foreground/80">
            <span className="inline-flex items-center gap-2">
              <ShieldCheck className="size-4" aria-hidden="true" />
              Server-managed sessions
            </span>
            <span className="inline-flex items-center gap-2">
              <LockKeyhole className="size-4" aria-hidden="true" />
              No tokens in browser storage
            </span>
          </div>
        </div>
        <p className="relative text-xs text-primary-foreground/60">
          EventFlow · Work Management
        </p>
      </section>

      <section className="flex items-center justify-center px-4 py-12 sm:px-8">
        <div className="w-full max-w-sm">
          <div className="mb-8 flex items-center gap-3 lg:hidden">
            <span className="flex size-10 items-center justify-center rounded-xl bg-primary text-sm font-bold text-primary-foreground">
              EF
            </span>
            <span className="text-lg font-semibold tracking-tight">EventFlow</span>
          </div>
          <h2 className="text-2xl font-semibold tracking-tight text-foreground">
            Sign in to your workspace
          </h2>
          <p className="mt-2 text-sm leading-relaxed text-muted-foreground">
            Continue with your organization&apos;s identity provider. EventFlow
            keeps your session in a secure, HTTP-only cookie.
          </p>

          <div className="mt-6 space-y-3">
            {expired ? (
              <Alert tone="warning" title="Your session expired">
                Sign in again to continue. Unsaved changes were not applied.
              </Alert>
            ) : null}
            {loggedOut ? (
              <Alert tone="success" title="You are signed out">
                Your browser session was ended successfully.
              </Alert>
            ) : null}
          </div>

          <Button
            className="mt-6 w-full"
            size="lg"
            onClick={handleLogin}
          >
            Continue to sign in
            <ArrowRight className="size-4" aria-hidden="true" />
          </Button>

          <p className="mt-4 text-center text-xs leading-relaxed text-muted-foreground">
            You will be redirected to your organization&apos;s identity
            provider. Access is managed by your workspace administrator.
          </p>
        </div>
      </section>
    </main>
  );
}

export function AuthCompletePage() {
  const { reloadSession, login, isAuthenticated } = useAuth();
  const navigate = useNavigate();
  const [error, setError] = useState<string | null>(null);
  const started = useRef(false);
  useDocumentTitle("Completing sign in");

  useEffect(() => {
    if (started.current) return;
    started.current = true;
    void reloadSession()
      .then((session) => {
        if (!session) {
          setError(
            "The sign-in flow did not create a valid browser session. Try again or contact your administrator.",
          );
          return;
        }
        let destination = "/";
        try {
          destination = safeReturnPath(sessionStorage.getItem(RETURN_TO_KEY));
          sessionStorage.removeItem(RETURN_TO_KEY);
        } catch {
          destination = "/";
        }
        window.location.replace(destination);
      })
      .catch((reason: unknown) => {
        setError(presentError(reason).description);
      });
  }, [reloadSession]);

  if (isAuthenticated && !error) {
    return (
      <div className="flex min-h-dvh items-center justify-center bg-background">
        <Spinner label="Finishing sign in" />
      </div>
    );
  }

  return (
    <main className="flex min-h-dvh items-center justify-center bg-background px-4">
      <div className="w-full max-w-md rounded-xl border border-border bg-surface p-8 shadow-sm">
        <h1 className="text-xl font-semibold text-foreground">
          {error ? "We could not complete sign in" : "Completing sign in"}
        </h1>
        {error ? (
          <>
            <p className="mt-2 text-sm text-muted-foreground">{error}</p>
            <Alert tone="warning" className="mt-4">
              If this keeps happening, confirm that the EventFlow API is running
              and that the configured post-login redirect points to{" "}
              <code className="font-mono text-xs">/auth/complete</code>.
            </Alert>
            <div className="mt-6 flex gap-2">
              <Button onClick={login}>Try signing in again</Button>
              <Button variant="outline" onClick={() => navigate("/login")}>
                Back to sign in
              </Button>
            </div>
          </>
        ) : (
          <div className="mt-4 flex items-center gap-3 text-sm text-muted-foreground">
            <Spinner label="Verifying your session" />
            Verifying your secure session...
          </div>
        )}
      </div>
    </main>
  );
}

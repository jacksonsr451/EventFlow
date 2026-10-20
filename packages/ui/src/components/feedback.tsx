import {
  AlertTriangle,
  CheckCircle2,
  Info,
  Loader2,
  RefreshCw,
  ShieldX,
  WifiOff,
  XCircle,
  type LucideIcon,
} from "lucide-react";
import type { ReactNode } from "react";
import { cn } from "../lib/cn";
import { Button } from "./button";

export type AlertTone = "info" | "success" | "warning" | "destructive";

const alertStyles: Record<AlertTone, string> = {
  info: "border-info/30 bg-info/10 text-foreground",
  success: "border-success/30 bg-success/10 text-foreground",
  warning: "border-warning/35 bg-warning/10 text-foreground",
  destructive: "border-destructive/35 bg-destructive/10 text-foreground",
};

const alertIcons: Record<AlertTone, LucideIcon> = {
  info: Info,
  success: CheckCircle2,
  warning: AlertTriangle,
  destructive: XCircle,
};

export interface AlertProps {
  tone?: AlertTone;
  title?: string;
  children: ReactNode;
  action?: ReactNode;
  className?: string;
}

export function Alert({
  tone = "info",
  title,
  children,
  action,
  className,
}: AlertProps) {
  const Icon = alertIcons[tone];
  return (
    <div
      role={tone === "destructive" ? "alert" : "status"}
      className={cn(
        "flex items-start gap-3 rounded-lg border px-4 py-3 text-sm",
        alertStyles[tone],
        className,
      )}
    >
      <Icon className="mt-0.5 size-4 shrink-0" aria-hidden="true" />
      <div className="min-w-0 flex-1">
        {title ? <p className="font-medium">{title}</p> : null}
        <div className={cn(title && "mt-1", "text-muted-foreground")}>
          {children}
        </div>
      </div>
      {action ? <div className="shrink-0">{action}</div> : null}
    </div>
  );
}

export function Spinner({
  label = "Loading",
  className,
}: {
  label?: string;
  className?: string;
}) {
  return (
    <span
      role="status"
      aria-live="polite"
      className={cn("inline-flex items-center gap-2 text-sm text-muted-foreground", className)}
    >
      <Loader2 className="size-4 animate-spin" aria-hidden="true" />
      <span className="sr-only">{label}</span>
    </span>
  );
}

export function Skeleton({ className }: { className?: string }) {
  return (
    <span
      aria-hidden="true"
      className={cn("block animate-pulse rounded-md bg-surface-muted", className)}
    />
  );
}

export interface EmptyStateProps {
  icon?: LucideIcon;
  title: string;
  description: string;
  action?: ReactNode;
  className?: string;
}

export function EmptyState({
  icon: Icon,
  title,
  description,
  action,
  className,
}: EmptyStateProps) {
  return (
    <div
      className={cn(
        "flex min-h-56 flex-col items-center justify-center rounded-lg border border-dashed border-border bg-surface/60 px-6 py-12 text-center",
        className,
      )}
    >
      {Icon ? (
        <span className="mb-4 flex size-11 items-center justify-center rounded-full bg-surface-muted text-muted-foreground">
          <Icon className="size-5" aria-hidden="true" />
        </span>
      ) : null}
      <h3 className="text-base font-semibold text-foreground">{title}</h3>
      <p className="mt-1.5 max-w-lg text-sm text-muted-foreground">
        {description}
      </p>
      {action ? <div className="mt-5">{action}</div> : null}
    </div>
  );
}

export interface ErrorStateProps {
  status?: number;
  title?: string;
  description?: string;
  correlationId?: string;
  onRetry?: () => void;
  action?: ReactNode;
  className?: string;
}

export function ErrorState({
  status,
  title,
  description,
  correlationId,
  onRetry,
  action,
  className,
}: ErrorStateProps) {
  const Icon = status === 403 ? ShieldX : status === 0 ? WifiOff : AlertTriangle;
  const fallbackTitle =
    status === 403
      ? "You do not have access"
      : status === 404
        ? "Not found"
        : status === 401
          ? "Your session has expired"
          : "Something went wrong";
  return (
    <div
      role="alert"
      className={cn(
        "flex min-h-56 flex-col items-center justify-center rounded-lg border border-border bg-surface px-6 py-12 text-center",
        className,
      )}
    >
      <span className="mb-4 flex size-11 items-center justify-center rounded-full bg-destructive/10 text-destructive">
        <Icon className="size-5" aria-hidden="true" />
      </span>
      <h3 className="text-base font-semibold text-foreground">
        {title ?? fallbackTitle}
      </h3>
      <p className="mt-1.5 max-w-lg text-sm text-muted-foreground">
        {description ??
          "The request could not be completed. Try again, or contact your workspace administrator if the problem continues."}
      </p>
      {correlationId ? (
        <p className="mt-3 font-mono text-xs text-muted-foreground">
          Correlation: {correlationId}
        </p>
      ) : null}
      {onRetry || action ? (
        <div className="mt-5 flex flex-wrap items-center justify-center gap-2">
          {onRetry ? (
            <Button variant="outline" onClick={onRetry}>
              <RefreshCw className="size-4" aria-hidden="true" />
              Try again
            </Button>
          ) : null}
          {action}
        </div>
      ) : null}
    </div>
  );
}

export function PageLoading({ label = "Loading page" }: { label?: string }) {
  return (
    <div className="space-y-6" aria-busy="true">
      <div className="space-y-3">
        <Skeleton className="h-7 w-56" />
        <Skeleton className="h-4 w-96 max-w-full" />
      </div>
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        {Array.from({ length: 4 }, (_, index) => (
          <Skeleton key={index} className="h-28" />
        ))}
      </div>
      <Skeleton className="h-72" />
      <span className="sr-only" role="status" aria-live="polite">
        {label}
      </span>
    </div>
  );
}

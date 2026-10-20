import type { HTMLAttributes, TdHTMLAttributes, ThHTMLAttributes } from "react";
import { cn } from "../lib/cn";

export type BadgeTone =
  | "neutral"
  | "info"
  | "success"
  | "warning"
  | "destructive"
  | "accent";

const badgeTones: Record<BadgeTone, string> = {
  neutral: "border-border bg-surface-muted text-foreground",
  info: "border-info/35 bg-info/10 text-info",
  success: "border-success/35 bg-success/10 text-success",
  warning: "border-warning/40 bg-warning/10 text-warning",
  destructive: "border-destructive/35 bg-destructive/10 text-destructive",
  accent: "border-primary/30 bg-primary/10 text-primary",
};

export interface BadgeProps extends HTMLAttributes<HTMLSpanElement> {
  tone?: BadgeTone;
}

export function Badge({ className, tone = "neutral", ...props }: BadgeProps) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-full border px-2 py-0.5 text-xs font-medium leading-5 whitespace-nowrap",
        badgeTones[tone],
        className,
      )}
      {...props}
    />
  );
}

export interface AvatarProps {
  name: string;
  className?: string;
}

export function Avatar({ name, className }: AvatarProps) {
  const initials = name
    .split(/[\s_-]+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((part) => part[0]?.toUpperCase())
    .join("");
  return (
    <span
      className={cn(
        "inline-flex size-8 shrink-0 items-center justify-center rounded-full bg-primary/10 text-xs font-semibold text-primary ring-1 ring-primary/15",
        className,
      )}
      aria-hidden="true"
      title={name}
    >
      {initials || "?"}
    </span>
  );
}

export function Card({ className, ...props }: HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      className={cn(
        "rounded-lg border border-border bg-surface shadow-sm",
        className,
      )}
      {...props}
    />
  );
}

export function CardHeader({
  className,
  ...props
}: HTMLAttributes<HTMLDivElement>) {
  return <div className={cn("space-y-1 p-5", className)} {...props} />;
}

export function CardTitle({
  className,
  ...props
}: HTMLAttributes<HTMLHeadingElement>) {
  return (
    <h2
      className={cn("text-base font-semibold text-foreground", className)}
      {...props}
    />
  );
}

export function CardDescription({
  className,
  ...props
}: HTMLAttributes<HTMLParagraphElement>) {
  return (
    <p className={cn("text-sm text-muted-foreground", className)} {...props} />
  );
}

export function CardContent({
  className,
  ...props
}: HTMLAttributes<HTMLDivElement>) {
  return <div className={cn("px-5 pb-5", className)} {...props} />;
}

export function CardFooter({
  className,
  ...props
}: HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      className={cn("flex items-center gap-2 border-t border-border px-5 py-3", className)}
      {...props}
    />
  );
}

export function TableContainer({
  className,
  ...props
}: HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      className={cn(
        "w-full overflow-x-auto rounded-lg border border-border bg-surface",
        className,
      )}
      {...props}
    />
  );
}

export function Table({ className, ...props }: HTMLAttributes<HTMLTableElement>) {
  return (
    <table
      className={cn("w-full min-w-[42rem] border-collapse text-sm", className)}
      {...props}
    />
  );
}

export function TableHead({
  className,
  ...props
}: HTMLAttributes<HTMLTableSectionElement>) {
  return (
    <thead
      className={cn("bg-surface-muted text-left text-xs uppercase tracking-wide text-muted-foreground", className)}
      {...props}
    />
  );
}

export function TableBody({
  className,
  ...props
}: HTMLAttributes<HTMLTableSectionElement>) {
  return <tbody className={cn("divide-y divide-border", className)} {...props} />;
}

export function TableRow({
  className,
  ...props
}: HTMLAttributes<HTMLTableRowElement>) {
  return (
    <tr
      className={cn("transition-colors hover:bg-surface-muted/70", className)}
      {...props}
    />
  );
}

export function TableHeaderCell({
  className,
  ...props
}: ThHTMLAttributes<HTMLTableCellElement>) {
  return (
    <th
      scope="col"
      className={cn("px-4 py-3 font-medium", className)}
      {...props}
    />
  );
}

export function TableCell({
  className,
  ...props
}: TdHTMLAttributes<HTMLTableCellElement>) {
  return (
    <td
      className={cn("px-4 py-3 align-middle text-foreground", className)}
      {...props}
    />
  );
}

const statusLabels: Record<string, string> = {
  draft: "Draft",
  open: "Open",
  triaging: "Triaging",
  proposed: "Proposed",
  duplicate: "Duplicate",
  rejected: "Rejected",
  closed: "Closed",
  reopened: "Reopened",
  in_review: "In review",
  approved: "Approved",
  changes_requested: "Changes requested",
  superseded: "Superseded",
  ready: "Ready",
  in_progress: "In progress",
  blocked: "Blocked",
  done: "Done",
  cancelled: "Cancelled",
  active: "Active",
  deprecated: "Deprecated",
  archived: "Archived",
  published: "Published",
  revoked: "Revoked",
  inactive: "Inactive",
  verified: "Verified",
  configured: "Configured",
};

const statusTones: Record<string, BadgeTone> = {
  draft: "neutral",
  open: "info",
  triaging: "warning",
  proposed: "accent",
  duplicate: "neutral",
  rejected: "destructive",
  closed: "neutral",
  reopened: "warning",
  in_review: "warning",
  approved: "success",
  changes_requested: "warning",
  superseded: "neutral",
  ready: "info",
  in_progress: "accent",
  blocked: "destructive",
  done: "success",
  cancelled: "neutral",
  active: "success",
  deprecated: "warning",
  archived: "neutral",
  published: "success",
  revoked: "destructive",
  inactive: "neutral",
  verified: "success",
  configured: "info",
};

export function humanizeStatus(status: string): string {
  return (
    statusLabels[status] ??
    status
      .replaceAll("_", " ")
      .replace(/\b\w/g, (letter) => letter.toUpperCase())
  );
}

export function StatusBadge({
  status,
  className,
}: {
  status: string;
  className?: string;
}) {
  return (
    <Badge tone={statusTones[status] ?? "neutral"} className={className}>
      <span
        className="size-1.5 rounded-full bg-current"
        aria-hidden="true"
      />
      {humanizeStatus(status)}
    </Badge>
  );
}

const priorityLabels: Record<string, string> = {
  critical: "Critical",
  high: "High",
  medium: "Medium",
  low: "Low",
};

const priorityTones: Record<string, BadgeTone> = {
  critical: "destructive",
  high: "warning",
  medium: "info",
  low: "neutral",
};

export function PriorityBadge({
  priority,
  className,
}: {
  priority: string;
  className?: string;
}) {
  return (
    <Badge tone={priorityTones[priority] ?? "neutral"} className={className}>
      <span className="font-mono text-[0.65rem] uppercase" aria-hidden="true">
        P
      </span>
      {priorityLabels[priority] ?? priority}
    </Badge>
  );
}

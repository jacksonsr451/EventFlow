import type { ReactNode } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@eventflow/ui";

export function DetailField({
  label,
  children,
}: {
  label: string;
  children: ReactNode;
}) {
  return (
    <div>
      <dt className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
        {label}
      </dt>
      <dd className="mt-1 text-sm text-foreground">{children}</dd>
    </div>
  );
}

export function DetailSection({
  title,
  children,
  action,
}: {
  title: string;
  children: ReactNode;
  action?: ReactNode;
}) {
  return (
    <Card>
      <CardHeader className="flex-row items-center justify-between space-y-0">
        <CardTitle>{title}</CardTitle>
        {action}
      </CardHeader>
      <CardContent className="text-sm leading-relaxed text-foreground">
        {children}
      </CardContent>
    </Card>
  );
}

export function Prose({ children }: { children: string | null | undefined }) {
  if (!children?.trim()) {
    return <p className="text-muted-foreground">Not provided.</p>;
  }
  return <p className="whitespace-pre-wrap break-words">{children}</p>;
}

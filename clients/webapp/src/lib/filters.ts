import type { URLSearchParamsInit } from "react-router-dom";

export function enumParam<const T extends string>(
  params: URLSearchParams,
  key: string,
  allowed: readonly T[],
): T | undefined {
  const value = params.get(key);
  return value && (allowed as readonly string[]).includes(value)
    ? (value as T)
    : undefined;
}

export function withParam(
  params: URLSearchParams,
  key: string,
  value: string | null | undefined,
): URLSearchParamsInit {
  const next = new URLSearchParams(params);
  if (value) {
    next.set(key, value);
  } else {
    next.delete(key);
  }
  return next;
}

export function withoutParams(
  params: URLSearchParams,
  keys: readonly string[],
): URLSearchParamsInit {
  const next = new URLSearchParams(params);
  for (const key of keys) next.delete(key);
  return next;
}

export const CONSULTATION_STATUSES = [
  "draft",
  "open",
  "triaging",
  "proposed",
  "duplicate",
  "rejected",
  "closed",
  "reopened",
] as const;

export const PROPOSAL_STATUSES = [
  "draft",
  "in_review",
  "approved",
  "rejected",
  "changes_requested",
  "superseded",
] as const;

export const WORK_ITEM_STATUSES = [
  "ready",
  "in_progress",
  "in_review",
  "blocked",
  "done",
  "cancelled",
] as const;

export const CATEGORIES = [
  "bug",
  "feature",
  "chore",
  "docs",
  "security",
] as const;

export const PRIORITIES = ["critical", "high", "medium", "low"] as const;

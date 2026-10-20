export function flattenPages<T>(
  pages: ReadonlyArray<{ items: T[] }> | undefined,
): T[] {
  return pages?.flatMap((page) => page.items) ?? [];
}

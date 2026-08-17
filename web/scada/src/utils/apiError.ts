export function apiErrorStatus(err: unknown): number | null {
  if (err instanceof Error) {
    const m = /^API Error (\d+):/.exec(err.message);
    if (m) return Number(m[1]);
  }
  return null;
}

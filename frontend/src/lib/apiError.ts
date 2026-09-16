/**
 * The message an API error carries, if it carries one.
 *
 * FastAPI puts a human-readable reason in `detail` — which toggle to change,
 * how many tickets are in the way. Pulling it out without `any` keeps the
 * reason on screen instead of falling back to a generic failure string.
 */
export function apiErrorDetail(error: unknown): string | null {
  const detail = (error as { response?: { data?: { detail?: unknown } } })
    ?.response?.data?.detail;
  return typeof detail === "string" && detail ? detail : null;
}

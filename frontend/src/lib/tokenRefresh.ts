const BACKEND_URL = process.env.BACKEND_URL ?? "http://backend:8000";

export type Tokens = { access: string; refresh?: string };

async function refreshTokens(refresh: string): Promise<Tokens | null> {
  const res = await fetch(`${BACKEND_URL}/api/auth/refresh/`, {
    method: "POST",
    // Without it Django's SECURE_SSL_REDIRECT answers 301 to https://backend.
    headers: { "Content-Type": "application/json", "X-Forwarded-Proto": "https" },
    body: JSON.stringify({ refresh }),
  });
  if (!res.ok) return null;
  return (await res.json()) as Tokens;
}

// Refresh tokens rotate and the old one is blacklisted, so parallel 401s must share one
// refresh call instead of racing (the loser would get 401 and log the user out).
// The result is reused only briefly: long enough for requests fired together by one page
// load, short enough that a leaked old refresh token cannot be replayed for new tokens.
// shortcut: per-process memory, fine for the single frontend container; with several
// replicas move this to Redis.
const REUSE_MS = 5_000;
type Entry = { result: Promise<Tokens | null>; expires: number; tokens?: Tokens };
const refreshes = new Map<string, Entry>();

export function refreshOnce(refresh: string): Promise<Tokens | null> {
  const now = Date.now();
  for (const [token, entry] of refreshes) {
    if (entry.expires < now) refreshes.delete(token);
  }
  const cached = refreshes.get(refresh);
  if (cached) return cached.result;

  const result = refreshTokens(refresh).catch(() => null);
  const entry: Entry = { result, expires: now + REUSE_MS };
  refreshes.set(refresh, entry);
  void result.then((tokens) => {
    // Do not cache failures: a network blip must not block the next attempt.
    if (tokens) entry.tokens = tokens;
    else refreshes.delete(refresh);
  });
  return result;
}

/** On logout: drop cached results issued for or from this refresh token. */
export function forgetRefresh(refresh: string): void {
  for (const [token, entry] of refreshes) {
    if (token === refresh || entry.tokens?.refresh === refresh) refreshes.delete(token);
  }
}

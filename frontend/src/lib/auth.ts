export function setTokens(access: string, refresh: string): void {
  // Access token in a regular cookie (readable by JS for Authorization header)
  document.cookie = `access_token=${encodeURIComponent(access)}; path=/; SameSite=Lax; max-age=${60 * 60}`;
  // Store refresh token in httpOnly cookie via a server-side route handler
  void fetch("/auth-cookie/set-refresh", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ refresh }),
  });
}

export function clearTokens(): void {
  document.cookie = "access_token=; path=/; max-age=0";
  void fetch("/auth-cookie/clear", { method: "POST" });
}

export function isAuthenticated(): boolean {
  if (typeof document === "undefined") return false;
  return document.cookie.includes("access_token=");
}

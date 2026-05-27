export async function setTokens(access: string, refresh: string): Promise<void> {
  await Promise.all([
    fetch("/auth-cookie/set-access", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ access }),
    }),
    fetch("/auth-cookie/set-refresh", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ refresh }),
    }),
  ]);
}

export async function clearTokens(): Promise<void> {
  await fetch("/auth-cookie/logout", { method: "POST" });
}

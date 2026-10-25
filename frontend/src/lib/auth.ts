export async function clearTokens(): Promise<void> {
  await fetch("/auth-cookie/logout", { method: "POST" });
}

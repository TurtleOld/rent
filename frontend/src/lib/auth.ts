export async function clearTokens(): Promise<void> {
  // Маршрут выхода принимает только JSON: иначе навязанный с чужого сайта выход был бы возможен.
  await fetch("/auth-cookie/logout", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: "{}",
  });
}

import { NextRequest, NextResponse } from "next/server";

/**
 * Проверяет, что запрос отправлен с JSON-телом.
 *
 * Чужой сайт не отправит JSON без CORS-preflight, поэтому правило JSON-only
 * отсекает навязанные запросы с других origin (вход и выход).
 *
 * Args:
 *     request: Входящий запрос.
 *
 * Returns:
 *     True, если Content-Type запроса — application/json.
 */
export function isJsonRequest(request: NextRequest): boolean {
  return request.headers.get("content-type")?.startsWith("application/json") ?? false;
}

/**
 * Готовит ответ 415 на запрос без JSON.
 *
 * Returns:
 *     Ответ с русским сообщением «Ожидается JSON».
 */
export function jsonRequired(): NextResponse {
  return NextResponse.json({ detail: "Ожидается JSON" }, { status: 415 });
}

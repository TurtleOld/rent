const API_BASE = "/api";

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
    public data?: unknown,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

function getAccessToken(): string | null {
  if (typeof document === "undefined") return null;
  const match = document.cookie.match(/(?:^|; )access_token=([^;]*)/);
  return match ? decodeURIComponent(match[1]) : null;
}

function authHeaders(): HeadersInit {
  const token = getAccessToken();
  return token ? { Authorization: `Bearer ${token}` } : {};
}

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      ...options.headers,
    },
    credentials: "include",
  });

  if (!res.ok) {
    let data: unknown = null;
    try {
      data = await res.json();
    } catch {
      // ignore parse error
    }
    throw new ApiError(res.status, `API error ${res.status}`, data);
  }

  if (res.status === 204) return undefined as T;
  return res.json() as Promise<T>;
}

// ── Auth ──────────────────────────────────────────────────────────────────────

export interface AuthTokens {
  access: string;
  refresh: string;
}

export async function register(email: string, password: string): Promise<void> {
  await request("/auth/register/", {
    method: "POST",
    body: JSON.stringify({ email, password }),
  });
}

export async function login(email: string, password: string): Promise<AuthTokens> {
  return request<AuthTokens>("/auth/login/", {
    method: "POST",
    body: JSON.stringify({ email, password }),
  });
}

// ── Invoice types ─────────────────────────────────────────────────────────────

export interface LineItem {
  id: number;
  service_name: string;
  unit: string | null;
  quantity: string | null;
  tariff: string | null;
  amount_charged: string | null;
  recalculation: string | null;
  debt: string | null;
  amount: string | null;
  provider: string | null;
  meter_id: string | null;
  previous_reading: string | null;
  current_reading: string | null;
}

export interface Invoice {
  id: number;
  pdf_file: string;
  status: "processing" | "processed" | "failed";
  error_message: string | null;
  provider_name: string | null;
  account_number: string | null;
  payer_name: string | null;
  address: string | null;
  period_start: string | null;
  period_end: string | null;
  period_month: number | null;
  period_year: number | null;
  amount_due: string | null;
  amount_charged: string | null;
  amount_paid_ai: string | null;
  amount_recalculation: string | null;
  confidence: number | null;
  warnings: string[];
  payment_status: "unpaid" | "partially_paid" | "paid";
  total_paid: string;
  line_items: LineItem[];
  created_at: string;
  updated_at: string;
}

export interface PaginatedResponse<T> {
  count: number;
  next: string | null;
  previous: string | null;
  results: T[];
}

export async function getInvoices(page = 1): Promise<PaginatedResponse<Invoice>> {
  return request<PaginatedResponse<Invoice>>(`/invoices/?page=${page}`, {
    headers: authHeaders(),
  });
}

export async function uploadInvoice(file: File): Promise<Invoice> {
  const formData = new FormData();
  formData.append("pdf_file", file);
  const res = await fetch(`${API_BASE}/invoices/upload/`, {
    method: "POST",
    headers: authHeaders(),
    body: formData,
    credentials: "include",
  });
  if (!res.ok) {
    const data = await res.json().catch(() => null);
    throw new ApiError(res.status, "Upload failed", data);
  }
  return res.json() as Promise<Invoice>;
}

export async function getInvoice(id: number): Promise<Invoice> {
  return request<Invoice>(`/invoices/${id}/`, { headers: authHeaders() });
}

export async function patchInvoice(
  id: number,
  data: Partial<Invoice>,
): Promise<Invoice> {
  return request<Invoice>(`/invoices/${id}/`, {
    method: "PATCH",
    headers: authHeaders(),
    body: JSON.stringify(data),
  });
}

export async function deleteInvoice(id: number): Promise<void> {
  return request<void>(`/invoices/${id}/`, {
    method: "DELETE",
    headers: authHeaders(),
  });
}

// ── Payment types ─────────────────────────────────────────────────────────────

export interface Payment {
  id: number;
  invoice: number;
  user: number;
  amount: string;
  payment_date: string;
  note: string | null;
  created_at: string;
}

export async function getPayments(invoiceId: number): Promise<Payment[]> {
  const result = await request<PaginatedResponse<Payment> | Payment[]>(
    `/invoices/${invoiceId}/payments/`,
    { headers: authHeaders() },
  );
  if (Array.isArray(result)) return result;
  return (result as PaginatedResponse<Payment>).results;
}

export async function createPayment(
  invoiceId: number,
  data: { amount: string; payment_date: string; note?: string },
): Promise<Payment> {
  return request<Payment>(`/invoices/${invoiceId}/payments/`, {
    method: "POST",
    headers: authHeaders(),
    body: JSON.stringify(data),
  });
}

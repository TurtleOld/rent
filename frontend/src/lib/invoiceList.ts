export function upsertInvoice<T extends { id: number }>(invoices: T[], invoice: T): T[] {
  return invoices.some((item) => item.id === invoice.id)
    ? invoices.map((item) => (item.id === invoice.id ? invoice : item))
    : [invoice, ...invoices];
}

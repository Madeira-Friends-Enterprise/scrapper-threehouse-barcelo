export function formatCurrency(n: number | null, currency = "EUR"): string {
  if (n == null) return "—";
  return new Intl.NumberFormat("en-GB", { style: "currency", currency, maximumFractionDigits: 0 }).format(n);
}

export function formatDate(d: string): string {
  if (!d) return "";
  const [y, m, dd] = d.split("-");
  return `${y}-${m}-${dd}`;
}

export function hotelKey(brand: string, hotelId: string) {
  return `${brand}__${hotelId}`;
}

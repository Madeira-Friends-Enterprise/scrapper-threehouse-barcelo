export function formatCurrency(n: number | null, currency = "EUR"): string {
  if (n == null) return "—";
  return new Intl.NumberFormat("en-GB", { style: "currency", currency, maximumFractionDigits: 0 }).format(n);
}

export function formatDate(d: string): string {
  if (!d) return "";
  // Happy path: ISO "YYYY-MM-DD".
  const isoMatch = d.match(/^(\d{4})-(\d{2})-(\d{2})/);
  if (isoMatch) return `${isoMatch[1]}-${isoMatch[2]}-${isoMatch[3]}`;
  // Sheets sometimes returns dates as serial numbers ("46146") when the
  // column is formatted as Number. Convert from the Lotus 1-2-3 epoch
  // (origin 1899-12-30, which is what Excel/Sheets use). Falls through
  // to "—" for any other shape so we never render undefined-undefined.
  if (/^\d{4,6}$/.test(d)) {
    const days = Number(d);
    const epoch = Date.UTC(1899, 11, 30);
    const ms = epoch + days * 86400_000;
    const dt = new Date(ms);
    if (!isNaN(dt.getTime())) {
      const y = dt.getUTCFullYear();
      const m = String(dt.getUTCMonth() + 1).padStart(2, "0");
      const dd = String(dt.getUTCDate()).padStart(2, "0");
      return `${y}-${m}-${dd}`;
    }
  }
  return d;
}

export function hotelKey(brand: string, hotelId: string) {
  return `${brand}__${hotelId}`;
}

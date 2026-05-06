export function formatCurrency(n: number | null, currency = "EUR"): string {
  if (n == null) return "—";
  return new Intl.NumberFormat("en-GB", { style: "currency", currency, maximumFractionDigits: 0 }).format(n);
}

const MONTH_NAMES_EN = [
  "Jan", "Feb", "Mar", "Apr", "May", "Jun",
  "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
];

function _formatHumanDate(y: number, m: number, dd: number): string {
  // "5 May 2026"
  return `${dd} ${MONTH_NAMES_EN[m - 1] ?? "?"} ${y}`;
}

export function formatDate(d: string): string {
  if (!d) return "";
  // Happy path: ISO "YYYY-MM-DD".
  const iso = d.match(/^(\d{4})-(\d{2})-(\d{2})/);
  if (iso) return _formatHumanDate(Number(iso[1]), Number(iso[2]), Number(iso[3]));
  // Sheets sometimes returns dates as serial numbers ("46146") when the
  // column is formatted as Number. Convert from the Lotus 1-2-3 epoch
  // (origin 1899-12-30, which is what Excel/Sheets use). Falls through
  // to the raw string for any other shape so we never render
  // undefined-undefined.
  if (/^\d{4,6}$/.test(d)) {
    const days = Number(d);
    const epoch = Date.UTC(1899, 11, 30);
    const dt = new Date(epoch + days * 86400_000);
    if (!isNaN(dt.getTime())) {
      return _formatHumanDate(
        dt.getUTCFullYear(),
        dt.getUTCMonth() + 1,
        dt.getUTCDate(),
      );
    }
  }
  return d;
}

export function hotelKey(brand: string, hotelId: string) {
  return `${brand}__${hotelId}`;
}

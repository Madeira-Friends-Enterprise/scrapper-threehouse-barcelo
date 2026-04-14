export type PriceRow = {
  scrapedAt: string;
  brand: string;
  hotelName: string;
  hotelId: string;
  roomType: string;
  roomId: string;
  city: string;
  date: string;   // YYYY-MM-DD
  price: number | null;
  currency: string;
  available: boolean;
  minStay: number | null;
  sourceUrl: string;
};

export type HotelSummary = {
  brand: string;
  hotelName: string;
  hotelId: string;
  city: string;
  rowCount: number;
  avgPrice: number | null;
  minPrice: number | null;
  maxPrice: number | null;
};

export type DatasetMeta = {
  totalRows: number;
  lastScrapedAt: string | null;
  dateRange: { start: string | null; end: string | null };
  hotels: HotelSummary[];
};

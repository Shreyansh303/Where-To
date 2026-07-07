// Typed mirror of the backend's TripPlan JSON + API helpers.

export const API_URL =
  process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export interface TripRequestBody {
  origin: string;
  destination: string;
  destination_city: string;
  departure_date: string;
  return_date: string;
  budget: number;
  travelers: number;
}

export interface FlightSegment {
  departure_airport: string;
  departure_airport_name: string;
  departure_time: string;
  arrival_airport: string;
  arrival_airport_name: string;
  arrival_time: string;
  airline: string;
  flight_number: string;
  duration_minutes: number;
  travel_class: string | null;
}

export interface FlightOption {
  id: string;
  direction: "outbound" | "return";
  segments: FlightSegment[];
  total_duration_minutes: number;
  layover_airports: string[];
  price: number;
  currency: string;
  airline_logo: string | null;
  carbon_grams: number | null;
}

export interface HotelOption {
  id: string;
  name: string;
  description: string | null;
  rate_per_night: number | null;
  total_rate: number | null;
  currency: string;
  hotel_class: number | null;
  rating: number | null;
  review_count: number | null;
  amenities: string[];
  check_in_time: string | null;
  check_out_time: string | null;
  link: string | null;
  thumbnail: string | null;
  maps_url: string | null;
}

export interface POI {
  id: string;
  name: string;
  kind: "attraction" | "restaurant";
  rating: number | null;
  review_count: number | null;
  types: string[];
  price_level: number | null;
  address: string | null;
  est_visit_minutes: number;
  maps_url: string;
}

export interface ResolvedStop {
  poi: POI;
  arrive: string;
  depart: string;
  travel_from_prev_minutes: number;
  travel_mode: string;
  travel_is_estimate: boolean;
  meal: "breakfast" | "lunch" | "dinner" | null;
  note: string | null;
  est_entry_cost: string | null;
  est_entry_cost_source: string | null;
  is_full_day: boolean;
}

export interface PlanDay {
  date: string;
  weekday_name: string;
  stops: ResolvedStop[];
  extras: POI[];
  commentary: string | null;
}

export interface DataQualityNote {
  source: string;
  level: "ok" | "degraded" | "failed";
  message: string;
}

export interface TripPlan {
  request: TripRequestBody & { nights?: number };
  outbound_flight: FlightOption | null;
  return_flight: FlightOption | null;
  hotel: HotelOption | null;
  days: PlanDay[];
  getting_around: string | null;
  budget: {
    currency: string;
    total: number;
    flights_total: number | null;
    hotel_total: number | null;
    remaining_for_activities: number | null;
    est_meal_cost: string | null;
  };
  data_quality: DataQualityNote[];
  commentary: string | null;
  dropped_pois: string[];
}

export interface TripStatus {
  trip_id: string;
  status: "running" | "done" | "error";
  error: string | null;
  plan: TripPlan | null;
}

export interface StageEvent {
  stage: string;
  message: string;
  ts?: number;
  status?: string;
}

export async function createTrip(body: TripRequestBody): Promise<string> {
  const res = await fetch(`${API_URL}/api/trips`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    const detail = await res.text();
    throw new Error(`Trip request rejected: ${detail}`);
  }
  const data = await res.json();
  return data.trip_id as string;
}

export async function getTrip(tripId: string): Promise<TripStatus> {
  const res = await fetch(`${API_URL}/api/trips/${tripId}`);
  if (!res.ok) throw new Error(`Trip ${tripId} not found`);
  return res.json();
}

export function eventsUrl(tripId: string): string {
  return `${API_URL}/api/trips/${tripId}/events`;
}

export function formatMoney(amount: number, currency: string): string {
  return new Intl.NumberFormat("en-IN", {
    style: "currency",
    currency,
    maximumFractionDigits: 0,
  }).format(amount);
}

export function formatDuration(minutes: number): string {
  const h = Math.floor(minutes / 60);
  const m = minutes % 60;
  return h > 0 ? `${h}h ${m}m` : `${m}m`;
}

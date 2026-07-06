"use client";

import {
  FlightOption,
  PlanDay,
  ResolvedStop,
  TripPlan,
  formatDuration,
  formatMoney,
} from "@/lib/api";

const MEAL_EMOJI: Record<string, string> = {
  breakfast: "☕",
  lunch: "🥗",
  dinner: "🍷",
};

export default function PlanView({ plan }: { plan: TripPlan }) {
  const c = plan.budget.currency;
  return (
    <div className="mx-auto w-full max-w-3xl">
      <header className="mb-8 text-center">
        <h1 className="text-3xl font-bold tracking-tight text-slate-900">
          {plan.request.origin} → {plan.request.destination_city}
        </h1>
        <p className="mt-2 text-slate-500">
          {plan.request.departure_date} to {plan.request.return_date} ·{" "}
          {plan.request.travelers} traveler{plan.request.travelers > 1 && "s"}
        </p>
        {plan.commentary && (
          <p className="mx-auto mt-4 max-w-xl rounded-2xl bg-sky-50 px-5 py-4 text-sm leading-relaxed text-sky-900">
            🤖 {plan.commentary}
          </p>
        )}
      </header>

      <DataQuality plan={plan} />

      <section className="mb-6 grid gap-4 sm:grid-cols-2">
        {plan.outbound_flight && (
          <FlightCard flight={plan.outbound_flight} label="Outbound" />
        )}
        {plan.return_flight && (
          <FlightCard flight={plan.return_flight} label="Return" showPrice />
        )}
      </section>

      {plan.hotel && (
        <section className="mb-6">
          <Card>
            <div className="flex items-start justify-between gap-4">
              <div>
                <p className="text-xs font-semibold uppercase tracking-wide text-slate-400">
                  Your stay
                </p>
                <h3 className="mt-1 text-lg font-semibold text-slate-900">
                  🏨 {plan.hotel.name}
                  {plan.hotel.hotel_class && (
                    <span className="ml-2 text-sm font-normal text-amber-500">
                      {"★".repeat(plan.hotel.hotel_class)}
                    </span>
                  )}
                </h3>
                {plan.hotel.rating && (
                  <p className="mt-1 text-sm text-slate-500">
                    {plan.hotel.rating} rating
                    {plan.hotel.review_count &&
                      ` · ${plan.hotel.review_count.toLocaleString()} reviews`}
                  </p>
                )}
                {plan.hotel.amenities.length > 0 && (
                  <p className="mt-2 text-sm text-slate-500">
                    {plan.hotel.amenities.slice(0, 5).join(" · ")}
                  </p>
                )}
              </div>
              <div className="shrink-0 text-right">
                {plan.hotel.total_rate != null && (
                  <p className="text-xl font-bold text-slate-900">
                    {formatMoney(plan.hotel.total_rate, c)}
                  </p>
                )}
                {plan.hotel.rate_per_night != null && (
                  <p className="text-xs text-slate-400">
                    {formatMoney(plan.hotel.rate_per_night, c)}/night
                  </p>
                )}
              </div>
            </div>
          </Card>
        </section>
      )}

      <BudgetBar plan={plan} />

      <section className="mt-8">
        <h2 className="mb-4 text-xl font-bold text-slate-900">
          Day by day 🗓️
        </h2>
        <div className="flex flex-col gap-5">
          {plan.days.map((day) => (
            <DayCard key={day.date} day={day} />
          ))}
        </div>
      </section>

      {plan.getting_around && (
        <section className="mt-6">
          <Card>
            <p className="text-xs font-semibold uppercase tracking-wide text-slate-400">
              Getting around
            </p>
            <p className="mt-2 text-sm leading-relaxed text-slate-600">
              🚇 {plan.getting_around}
            </p>
          </Card>
        </section>
      )}

      {plan.dropped_pois.length > 0 && (
        <section className="mt-6">
          <Card>
            <p className="text-xs font-semibold uppercase tracking-wide text-slate-400">
              Didn&apos;t make the cut
            </p>
            <ul className="mt-2 flex flex-col gap-1 text-sm text-slate-500">
              {plan.dropped_pois.map((d) => (
                <li key={d}>· {d}</li>
              ))}
            </ul>
          </Card>
        </section>
      )}
    </div>
  );
}

function Card({ children }: { children: React.ReactNode }) {
  return (
    <div className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
      {children}
    </div>
  );
}

function FlightCard({
  flight,
  label,
  showPrice = false,
}: {
  flight: FlightOption;
  label: string;
  showPrice?: boolean;
}) {
  const first = flight.segments[0];
  const last = flight.segments[flight.segments.length - 1];
  return (
    <Card>
      <div className="flex items-start justify-between">
        <p className="text-xs font-semibold uppercase tracking-wide text-slate-400">
          {label === "Outbound" ? "✈️" : "🛬"} {label}
        </p>
        {showPrice && (
          <p className="text-lg font-bold text-slate-900">
            {formatMoney(flight.price, flight.currency)}
            <span className="block text-right text-[10px] font-normal text-slate-400">
              round trip
            </span>
          </p>
        )}
      </div>
      <div className="mt-3 flex items-center gap-3">
        <div>
          <p className="text-lg font-bold text-slate-900">
            {first.departure_airport}
          </p>
          <p className="text-xs text-slate-400">{timeOf(first.departure_time)}</p>
        </div>
        <div className="flex-1 text-center">
          <p className="text-xs text-slate-400">
            {formatDuration(flight.total_duration_minutes)}
          </p>
          <div className="relative my-1 h-px bg-slate-200">
            <span className="absolute -top-1.5 left-1/2 -translate-x-1/2 text-xs">
              ✈
            </span>
          </div>
          <p className="text-xs text-slate-400">
            {flight.layover_airports.length === 0
              ? "non-stop"
              : `via ${flight.layover_airports.join(", ")}`}
          </p>
        </div>
        <div className="text-right">
          <p className="text-lg font-bold text-slate-900">
            {last.arrival_airport}
          </p>
          <p className="text-xs text-slate-400">{timeOf(last.arrival_time)}</p>
        </div>
      </div>
      <p className="mt-3 text-sm text-slate-500">
        {[...new Set(flight.segments.map((s) => s.airline))].join(" + ")}{" "}
        <span className="text-slate-300">·</span>{" "}
        {flight.segments.map((s) => s.flight_number).join(", ")}
      </p>
    </Card>
  );
}

function timeOf(dt: string): string {
  return dt.split(" ")[1] ?? dt;
}

function BudgetBar({ plan }: { plan: TripPlan }) {
  const { total, flights_total, hotel_total, remaining_for_activities, currency } =
    plan.budget;
  const flightsPct = ((flights_total ?? 0) / total) * 100;
  const hotelPct = ((hotel_total ?? 0) / total) * 100;
  const overBudget = (remaining_for_activities ?? 0) < 0;
  return (
    <Card>
      <div className="flex items-baseline justify-between">
        <p className="text-xs font-semibold uppercase tracking-wide text-slate-400">
          Budget
        </p>
        <p className="text-sm text-slate-500">
          total {formatMoney(total, currency)}
        </p>
      </div>
      <div className="mt-3 flex h-3 w-full overflow-hidden rounded-full bg-slate-100">
        <div
          className="bg-sky-500"
          style={{ width: `${Math.min(flightsPct, 100)}%` }}
          title="Flights"
        />
        <div
          className="bg-indigo-400"
          style={{ width: `${Math.min(hotelPct, 100 - flightsPct)}%` }}
          title="Hotel"
        />
      </div>
      <div className="mt-3 flex flex-wrap gap-x-6 gap-y-1 text-sm">
        <span className="text-slate-600">
          <Dot className="bg-sky-500" /> Flights:{" "}
          <b>{flights_total != null ? formatMoney(flights_total, currency) : "—"}</b>
        </span>
        <span className="text-slate-600">
          <Dot className="bg-indigo-400" /> Hotel:{" "}
          <b>{hotel_total != null ? formatMoney(hotel_total, currency) : "—"}</b>
        </span>
        <span className={overBudget ? "font-medium text-rose-600" : "text-slate-600"}>
          <Dot className={overBudget ? "bg-rose-500" : "bg-emerald-400"} />{" "}
          {overBudget ? "Over budget by " : "Left for fun: "}
          <b>
            {remaining_for_activities != null
              ? formatMoney(Math.abs(remaining_for_activities), currency)
              : "—"}
          </b>
        </span>
      </div>
    </Card>
  );
}

function Dot({ className }: { className: string }) {
  return (
    <span
      className={`mr-1 inline-block h-2.5 w-2.5 rounded-full align-middle ${className}`}
    />
  );
}

function DayCard({ day }: { day: PlanDay }) {
  return (
    <Card>
      <h3 className="font-semibold text-slate-900">
        {day.weekday_name}{" "}
        <span className="ml-1 text-sm font-normal text-slate-400">
          {day.date}
        </span>
      </h3>
      <ol className="mt-4 flex flex-col">
        {day.stops.map((stop, i) => (
          <StopRow key={`${stop.poi.id}-${i}`} stop={stop} isLast={i === day.stops.length - 1} />
        ))}
        {day.stops.length === 0 && (
          <p className="text-sm text-slate-400">
            Free day — no bookable attractions were available.
          </p>
        )}
      </ol>
    </Card>
  );
}

function StopRow({ stop, isLast }: { stop: ResolvedStop; isLast: boolean }) {
  const isMeal = stop.meal != null;
  return (
    <li className="relative flex gap-4 pb-1">
      <div className="flex flex-col items-center">
        <span
          className={`z-10 flex h-8 w-8 shrink-0 items-center justify-center rounded-full text-sm ${
            isMeal ? "bg-amber-100" : "bg-sky-100"
          }`}
        >
          {isMeal ? MEAL_EMOJI[stop.meal!] : "📍"}
        </span>
        {!isLast && <span className="w-px flex-1 bg-slate-200" />}
      </div>
      <div className="pb-4">
        <p className="text-xs font-medium text-slate-400">
          {stop.arrive} – {stop.depart}
          {stop.travel_from_prev_minutes > 0 && (
            <span className="ml-2 text-slate-300">
              · {stop.travel_is_estimate ? "~" : ""}
              {stop.travel_from_prev_minutes}m travel
            </span>
          )}
        </p>
        <p className="font-medium text-slate-800">
          {stop.poi.name}
          {isMeal && (
            <span className="ml-2 rounded-full bg-amber-50 px-2 py-0.5 text-xs font-normal text-amber-600">
              {stop.meal}
            </span>
          )}
        </p>
        {stop.poi.rating != null && (
          <p className="text-xs text-slate-400">
            ★ {stop.poi.rating}
            {stop.poi.review_count &&
              ` (${stop.poi.review_count.toLocaleString()})`}
            {stop.poi.address && ` · ${stop.poi.address}`}
          </p>
        )}
        {stop.note && (
          <p className="mt-1 text-xs text-amber-600">⚠ {stop.note}</p>
        )}
      </div>
    </li>
  );
}

function DataQuality({ plan }: { plan: TripPlan }) {
  const notes = plan.data_quality.filter((n) => n.level !== "ok");
  if (notes.length === 0) return null;
  return (
    <div className="mb-6 rounded-2xl border border-amber-200 bg-amber-50 px-5 py-4">
      <p className="text-xs font-semibold uppercase tracking-wide text-amber-600">
        Heads up
      </p>
      <ul className="mt-1 flex flex-col gap-1 text-sm text-amber-800">
        {notes.map((n, i) => (
          <li key={i}>· {n.message}</li>
        ))}
      </ul>
    </div>
  );
}

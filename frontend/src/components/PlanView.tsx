"use client";

import {
  FlightOption,
  PlanDay,
  POI,
  ResolvedStop,
  TripPlan,
  formatDuration,
  formatMoney,
} from "@/lib/api";

export default function PlanView({ plan }: { plan: TripPlan }) {
  const c = plan.budget.currency;
  return (
    <div className="mx-auto w-full max-w-3xl">
      <header className="mb-8 text-center">
        <h1 className="text-3xl font-bold tracking-tight text-slate-900 dark:text-slate-100">
          {plan.request.origin} → {plan.request.destination_city}
        </h1>
        <p className="mt-2 text-slate-500 dark:text-slate-400">
          {plan.request.departure_date} to {plan.request.return_date} ·{" "}
          {plan.request.travelers} traveler{plan.request.travelers > 1 && "s"}
        </p>
        {plan.commentary && (
          <p className="mx-auto mt-4 max-w-xl rounded-2xl bg-sky-50 px-5 py-4 text-sm leading-relaxed text-sky-900 dark:bg-sky-950 dark:text-sky-200">
            {plan.commentary}
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
                <p className="text-xs font-semibold uppercase tracking-wide text-slate-400 dark:text-slate-500">
                  Your stay
                </p>
                <h3 className="mt-1 flex items-center gap-2 text-lg font-semibold text-slate-900 dark:text-slate-100">
                  {plan.hotel.name}
                  {plan.hotel.maps_url && <MapsLink href={plan.hotel.maps_url} />}
                </h3>
                {plan.hotel.hotel_class && (
                  <p className="text-sm text-amber-500">
                    {"★".repeat(plan.hotel.hotel_class)}
                  </p>
                )}
                {plan.hotel.rating && (
                  <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">
                    {plan.hotel.rating} rating
                    {plan.hotel.review_count &&
                      ` · ${plan.hotel.review_count.toLocaleString()} reviews`}
                  </p>
                )}
                {plan.hotel.amenities.length > 0 && (
                  <p className="mt-2 text-sm text-slate-500 dark:text-slate-400">
                    {plan.hotel.amenities.slice(0, 5).join(" · ")}
                  </p>
                )}
              </div>
              <div className="shrink-0 text-right">
                {plan.hotel.total_rate != null && (
                  <p className="text-xl font-bold text-slate-900 dark:text-slate-100">
                    {formatMoney(plan.hotel.total_rate, c)}
                  </p>
                )}
                {plan.hotel.rate_per_night != null && (
                  <p className="text-xs text-slate-400 dark:text-slate-500">
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
        <h2 className="mb-4 text-xl font-bold text-slate-900 dark:text-slate-100">
          Day by day
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
            <p className="text-xs font-semibold uppercase tracking-wide text-slate-400 dark:text-slate-500">
              Getting around
            </p>
            <p className="mt-2 text-sm leading-relaxed text-slate-600 dark:text-slate-300">
              {plan.getting_around}
            </p>
          </Card>
        </section>
      )}

      {plan.dropped_pois.length > 0 && (
        <section className="mt-6">
          <Card>
            <p className="text-xs font-semibold uppercase tracking-wide text-slate-400 dark:text-slate-500">
              Didn&apos;t make the cut
            </p>
            <ul className="mt-2 flex flex-col gap-1 text-sm text-slate-500 dark:text-slate-400">
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
    <div className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm dark:border-slate-800 dark:bg-slate-900">
      {children}
    </div>
  );
}

/* Small chip linking a place to Google Maps. */
function MapsLink({ href }: { href: string }) {
  return (
    <a
      href={href}
      target="_blank"
      rel="noopener noreferrer"
      title="Open in Google Maps"
      className="inline-flex shrink-0 items-center gap-1 rounded-md border border-slate-200 bg-slate-50 px-1.5 py-0.5 text-[10px] font-medium text-slate-500 transition hover:border-sky-300 hover:text-sky-600 dark:border-slate-700 dark:bg-slate-800 dark:text-slate-400 dark:hover:border-sky-700 dark:hover:text-sky-400"
    >
      <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
        <path d="M7 17 17 7M8 7h9v9" />
      </svg>
      Maps
    </a>
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
        <p className="text-xs font-semibold uppercase tracking-wide text-slate-400 dark:text-slate-500">
          {label}
        </p>
        {showPrice && (
          <p className="text-lg font-bold text-slate-900 dark:text-slate-100">
            {formatMoney(flight.price, flight.currency)}
            <span className="block text-right text-[10px] font-normal text-slate-400 dark:text-slate-500">
              round trip
            </span>
          </p>
        )}
      </div>
      <div className="mt-3 flex items-center gap-3">
        <div>
          <p className="text-lg font-bold text-slate-900 dark:text-slate-100">
            {first.departure_airport}
          </p>
          <p className="text-xs text-slate-400 dark:text-slate-500">
            {timeOf(first.departure_time)}
          </p>
        </div>
        <div className="flex-1 text-center">
          <p className="text-xs text-slate-400 dark:text-slate-500">
            {formatDuration(flight.total_duration_minutes)}
          </p>
          <div className="my-1 h-px bg-slate-200 dark:bg-slate-700" />
          <p className="text-xs text-slate-400 dark:text-slate-500">
            {flight.layover_airports.length === 0
              ? "non-stop"
              : `via ${flight.layover_airports.join(", ")}`}
          </p>
        </div>
        <div className="text-right">
          <p className="text-lg font-bold text-slate-900 dark:text-slate-100">
            {last.arrival_airport}
          </p>
          <p className="text-xs text-slate-400 dark:text-slate-500">
            {timeOf(last.arrival_time)}
          </p>
        </div>
      </div>
      <p className="mt-3 text-sm text-slate-500 dark:text-slate-400">
        {[...new Set(flight.segments.map((s) => s.airline))].join(" + ")}{" "}
        <span className="text-slate-300 dark:text-slate-600">·</span>{" "}
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
        <p className="text-xs font-semibold uppercase tracking-wide text-slate-400 dark:text-slate-500">
          Budget
        </p>
        <p className="text-sm text-slate-500 dark:text-slate-400">
          total {formatMoney(total, currency)}
        </p>
      </div>
      <div className="mt-3 flex h-3 w-full overflow-hidden rounded-full bg-slate-100 dark:bg-slate-800">
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
        <span className="text-slate-600 dark:text-slate-300">
          <Dot className="bg-sky-500" /> Flights:{" "}
          <b>{flights_total != null ? formatMoney(flights_total, currency) : "—"}</b>
        </span>
        <span className="text-slate-600 dark:text-slate-300">
          <Dot className="bg-indigo-400" /> Hotel:{" "}
          <b>{hotel_total != null ? formatMoney(hotel_total, currency) : "—"}</b>
        </span>
        <span
          className={
            overBudget
              ? "font-medium text-rose-600 dark:text-rose-400"
              : "text-slate-600 dark:text-slate-300"
          }
        >
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
  const extras = day.extras ?? []; // tolerate plans from an older backend
  return (
    <Card>
      <h3 className="font-semibold text-slate-900 dark:text-slate-100">
        {day.weekday_name}{" "}
        <span className="ml-1 text-sm font-normal text-slate-400 dark:text-slate-500">
          {day.date}
        </span>
      </h3>
      <ol className="mt-4 flex flex-col">
        {day.stops.map((stop, i) => (
          <StopRow
            key={`${stop.poi.id}-${i}`}
            stop={stop}
            isLast={i === day.stops.length - 1}
          />
        ))}
        {day.stops.length === 0 && (
          <p className="text-sm text-slate-400 dark:text-slate-500">
            Free day — no bookable attractions were available.
          </p>
        )}
      </ol>
      {extras.length > 0 && (
        <div className="mt-4 rounded-xl bg-slate-50 px-4 py-3 dark:bg-slate-800/60">
          <p className="text-xs font-semibold uppercase tracking-wide text-slate-400 dark:text-slate-500">
            If you have time
          </p>
          <ul className="mt-2 flex flex-col gap-1.5">
            {extras.map((poi) => (
              <ExtraRow key={poi.id} poi={poi} />
            ))}
          </ul>
        </div>
      )}
    </Card>
  );
}

function ExtraRow({ poi }: { poi: POI }) {
  return (
    <li className="flex items-center gap-2 text-sm">
      <span className="text-slate-700 dark:text-slate-300">{poi.name}</span>
      {poi.rating != null && (
        <span className="text-xs text-slate-400 dark:text-slate-500">
          ★ {poi.rating}
        </span>
      )}
      {poi.maps_url && <MapsLink href={poi.maps_url} />}
    </li>
  );
}

function StopRow({ stop, isLast }: { stop: ResolvedStop; isLast: boolean }) {
  const isMeal = stop.meal != null;
  return (
    <li className="relative flex gap-4 pb-1">
      <div className="flex flex-col items-center">
        <span
          className={`z-10 flex h-8 w-8 shrink-0 items-center justify-center rounded-full ${
            isMeal
              ? "bg-amber-100 text-amber-600 dark:bg-amber-950 dark:text-amber-400"
              : "bg-sky-100 text-sky-600 dark:bg-sky-950 dark:text-sky-400"
          }`}
        >
          {isMeal ? <ForkIcon /> : <PinIcon />}
        </span>
        {!isLast && <span className="w-px flex-1 bg-slate-200 dark:bg-slate-700" />}
      </div>
      <div className="pb-4">
        <p className="text-xs font-medium text-slate-400 dark:text-slate-500">
          {stop.arrive} – {stop.depart}
          {stop.travel_from_prev_minutes > 0 && (
            <span className="ml-2 text-slate-300 dark:text-slate-600">
              · {stop.travel_is_estimate ? "~" : ""}
              {stop.travel_from_prev_minutes}m travel
            </span>
          )}
        </p>
        <p className="flex flex-wrap items-center gap-2 font-medium text-slate-800 dark:text-slate-200">
          {stop.poi.name}
          {stop.meal && (
            <span className="rounded-full bg-amber-50 px-2 py-0.5 text-xs font-normal text-amber-600 dark:bg-amber-950 dark:text-amber-400">
              {stop.meal}
            </span>
          )}
          {stop.poi.maps_url && <MapsLink href={stop.poi.maps_url} />}
        </p>
        {stop.poi.rating != null && (
          <p className="text-xs text-slate-400 dark:text-slate-500">
            ★ {stop.poi.rating}
            {stop.poi.review_count &&
              ` (${stop.poi.review_count.toLocaleString()})`}
            {stop.poi.address && ` · ${stop.poi.address}`}
          </p>
        )}
        {stop.note && (
          <p className="mt-1 text-xs text-amber-600 dark:text-amber-400">
            {stop.note}
          </p>
        )}
      </div>
    </li>
  );
}

function PinIcon() {
  return (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M20 10c0 6-8 12-8 12s-8-6-8-12a8 8 0 0 1 16 0z" />
      <circle cx="12" cy="10" r="3" />
    </svg>
  );
}

function ForkIcon() {
  return (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M3 2v7c0 1.1.9 2 2 2h4a2 2 0 0 0 2-2V2M7 2v20M21 15V2a5 5 0 0 0-5 5v6c0 1.1.9 2 2 2h3zm0 0v7" />
    </svg>
  );
}

function DataQuality({ plan }: { plan: TripPlan }) {
  const notes = plan.data_quality.filter((n) => n.level !== "ok");
  if (notes.length === 0) return null;
  return (
    <div className="mb-6 rounded-2xl border border-amber-200 bg-amber-50 px-5 py-4 dark:border-amber-900 dark:bg-amber-950/60">
      <p className="text-xs font-semibold uppercase tracking-wide text-amber-600 dark:text-amber-400">
        Heads up
      </p>
      <ul className="mt-1 flex flex-col gap-1 text-sm text-amber-800 dark:text-amber-200">
        {notes.map((n, i) => (
          <li key={i}>· {n.message}</li>
        ))}
      </ul>
    </div>
  );
}

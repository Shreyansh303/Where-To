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

  let numericMealCost = 0;
  if (plan.budget.est_meal_cost) {
    const match = plan.budget.est_meal_cost.match(/[\d,.]+/);
    if (match) {
      const num = parseFloat(match[0].replace(/,/g, ""));
      if (!isNaN(num)) numericMealCost = num;
    }
  }

  let currentRemaining = plan.budget.remaining_for_activities ?? 0;
  const dayStats = plan.days.map((day) => {
    let dayAttrSpent = 0;
    let dayMeals = 0;
    day.stops.forEach((stop) => {
      if (stop.est_entry_cost && stop.est_entry_cost.toLowerCase() !== "free") {
        const match = stop.est_entry_cost.match(/[\d,.]+/);
        if (match) {
          const num = parseFloat(match[0].replace(/,/g, ""));
          if (!isNaN(num)) dayAttrSpent += num;
        }
      }
      if (stop.meal) {
        dayMeals++;
      }
    });

    const totalAttrSpent = dayAttrSpent * plan.request.travelers;
    const totalMealSpent = dayMeals * numericMealCost * plan.request.travelers;
    const totalDaySpent = totalAttrSpent + totalMealSpent;

    currentRemaining -= totalDaySpent;
    return { totalAttrSpent, totalMealSpent, totalDaySpent, currentRemaining };
  });

  return (
    <div className="mx-auto w-full max-w-3xl">
      <header className="mb-8 text-center">
        <h1 className="text-3xl font-bold tracking-tight text-zinc-900 dark:text-zinc-100">
          {plan.request.origin} → {plan.request.destination_city}
        </h1>
        <p className="mt-2 text-zinc-500 dark:text-zinc-400">
          {plan.request.departure_date} to {plan.request.return_date} ·{" "}
          {plan.request.travelers} traveler{plan.request.travelers > 1 && "s"}
        </p>
        {plan.commentary && (
          <p className="mx-auto mt-4 max-w-xl rounded-2xl bg-emerald-50 px-5 py-4 text-sm leading-relaxed text-emerald-900 dark:bg-emerald-950/50 dark:text-emerald-200">
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
          <FlightCard flight={plan.return_flight} label="Return" priceNote="round trip" />
        )}
      </section>

      {plan.hotel && (
        <section className="mb-6">
          <Card>
            <div className="flex items-start justify-between gap-4">
              <div>
                <p className="text-xs font-semibold uppercase tracking-wide text-zinc-400 dark:text-zinc-500">
                  Your stay
                </p>
                <h3 className="mt-1 flex items-center gap-2 text-lg font-semibold text-zinc-900 dark:text-zinc-100">
                  {plan.hotel.name}
                  {plan.hotel.maps_url && <MapsLink href={plan.hotel.maps_url} />}
                </h3>
                {plan.hotel.hotel_class && (
                  <p className="text-sm text-amber-500">
                    {"★".repeat(plan.hotel.hotel_class)}
                  </p>
                )}
                {plan.hotel.rating && (
                  <p className="mt-1 text-sm text-zinc-500 dark:text-zinc-400">
                    {plan.hotel.rating} rating
                    {plan.hotel.review_count &&
                      ` · ${plan.hotel.review_count.toLocaleString()} reviews`}
                  </p>
                )}
                {plan.hotel.amenities.length > 0 && (
                  <p className="mt-2 text-sm text-zinc-500 dark:text-zinc-400">
                    {plan.hotel.amenities.slice(0, 5).join(" · ")}
                  </p>
                )}
              </div>
              <div className="shrink-0 text-right">
                {plan.hotel.total_rate != null && (
                  <p className="text-xl font-bold text-zinc-900 dark:text-zinc-100">
                    {formatMoney(plan.hotel.total_rate, c)}
                  </p>
                )}
                {plan.hotel.rate_per_night != null && (
                  <p className="text-xs text-zinc-400 dark:text-zinc-500">
                    {formatMoney(plan.hotel.rate_per_night, c)}/night
                  </p>
                )}
              </div>
            </div>
          </Card>
        </section>
      )}

      <BudgetBar plan={plan} />

      {plan.getting_around && (
        <section className="mt-6">
          <Card>
            <p className="text-xs font-semibold uppercase tracking-wide text-zinc-400 dark:text-zinc-500">
              Getting around
            </p>
            <p className="mt-2 text-sm leading-relaxed text-zinc-600 dark:text-zinc-300">
              {plan.getting_around}
            </p>
          </Card>
        </section>
      )}

      <section className="mt-8">
        <h2 className="mb-4 text-xl font-bold text-zinc-900 dark:text-zinc-100">
          Day by day
        </h2>
        <div className="flex flex-col gap-5">
          {plan.days.map((day, i) => (
            <DayCard
              key={day.date}
              day={day}
              spentAttr={dayStats[i].totalAttrSpent}
              spentFood={dayStats[i].totalMealSpent}
              spentTotal={dayStats[i].totalDaySpent}
              remaining={dayStats[i].currentRemaining}
              currency={c}
            />
          ))}
        </div>
      </section>

      {plan.dropped_pois.length > 0 && (
        <section className="mt-6">
          <Card>
            <p className="text-xs font-semibold uppercase tracking-wide text-zinc-400 dark:text-zinc-500">
              Didn&apos;t make the cut
            </p>
            <ul className="mt-2 flex flex-col gap-1 text-sm text-zinc-500 dark:text-zinc-400">
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
    <div className="rounded-2xl border border-zinc-200 bg-white p-5 shadow-sm dark:border-zinc-800 dark:bg-zinc-900">
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
      className="inline-flex shrink-0 items-center gap-1 rounded-md border border-zinc-200 bg-zinc-50 px-1.5 py-0.5 text-[10px] font-medium text-zinc-500 transition hover:border-emerald-300 hover:text-emerald-600 dark:border-zinc-700 dark:bg-zinc-800 dark:text-zinc-400 dark:hover:border-emerald-700 dark:hover:text-emerald-400"
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
  priceNote,
}: {
  flight: FlightOption;
  label: string;
  priceNote?: string;
}) {
  const first = flight.segments[0];
  const last = flight.segments[flight.segments.length - 1];
  return (
    <Card>
      <div className="flex min-h-[2.75rem] items-start justify-between">
        <p className="text-xs font-semibold uppercase tracking-wide text-zinc-400 dark:text-zinc-500">
          {label}
        </p>
        {priceNote && (
          <div className="text-right">
            <p className="text-lg font-bold text-zinc-900 dark:text-zinc-100">
              {formatMoney(flight.price, flight.currency)}
            </p>
            <p className="text-[10px] font-normal text-zinc-400 dark:text-zinc-500">
              {priceNote}
            </p>
          </div>
        )}
      </div>
      <div className="mt-3 flex items-center gap-3">
        <div>
          <p className="text-lg font-bold text-zinc-900 dark:text-zinc-100">
            {first.departure_airport}
          </p>
          <p className="text-xs text-zinc-400 dark:text-zinc-500">
            {timeOf(first.departure_time)}
          </p>
          {first.departure_airport_name && (
            <p className="mt-0.5 max-w-[7rem] truncate text-[10px] text-zinc-400 dark:text-zinc-600" title={first.departure_airport_name}>
              {first.departure_airport_name}
            </p>
          )}
        </div>
        <div className="flex-1 text-center">
          <p className="text-xs text-zinc-400 dark:text-zinc-500">
            {formatDuration(flight.total_duration_minutes)}
          </p>
          <div className="my-1 h-px bg-zinc-200 dark:bg-zinc-700" />
          <p className="text-xs text-zinc-400 dark:text-zinc-500">
            {flight.layover_airports.length === 0
              ? "non-stop"
              : `via ${flight.layover_airports.join(", ")}`}
          </p>
        </div>
        <div className="text-right">
          <p className="text-lg font-bold text-zinc-900 dark:text-zinc-100">
            {last.arrival_airport}
          </p>
          <p className="text-xs text-zinc-400 dark:text-zinc-500">
            {timeOf(last.arrival_time)}
          </p>
          {last.arrival_airport_name && (
            <p className="mt-0.5 max-w-[7rem] truncate text-[10px] text-zinc-400 dark:text-zinc-600" title={last.arrival_airport_name}>
              {last.arrival_airport_name}
            </p>
          )}
        </div>
      </div>
      <p className="mt-3 text-sm text-zinc-500 dark:text-zinc-400">
        {[...new Set(flight.segments.map((s) => s.airline))].join(" + ")}{" "}
        <span className="text-zinc-300 dark:text-zinc-600">·</span>{" "}
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
        <p className="text-xs font-semibold uppercase tracking-wide text-zinc-400 dark:text-zinc-500">
          Budget
        </p>
        <p className="text-sm text-zinc-500 dark:text-zinc-400">
          total {formatMoney(total, currency)}
        </p>
      </div>
      <div className="mt-3 flex h-3 w-full overflow-hidden rounded-full bg-zinc-100 dark:bg-zinc-800">
        <div
          className="bg-cyan-500"
          style={{ width: `${Math.min(flightsPct, 100)}%` }}
          title="Flights"
        />
        <div
          className="bg-violet-500"
          style={{ width: `${Math.min(hotelPct, 100 - flightsPct)}%` }}
          title="Hotel"
        />
      </div>
      <div className="mt-3 flex flex-wrap gap-x-6 gap-y-1 text-sm">
        <span className="text-zinc-600 dark:text-zinc-300">
          <Dot className="bg-cyan-500" /> Flights:{" "}
          <b>{flights_total != null ? formatMoney(flights_total, currency) : "—"}</b>
        </span>
        <span className="text-zinc-600 dark:text-zinc-300">
          <Dot className="bg-violet-500" /> Hotel:{" "}
          <b>{hotel_total != null ? formatMoney(hotel_total, currency) : "—"}</b>
        </span>
        <span
          className={
            overBudget
              ? "font-medium text-rose-600 dark:text-rose-400"
              : "text-zinc-600 dark:text-zinc-300"
          }
        >
          <Dot className={overBudget ? "bg-rose-500" : "bg-amber-400"} />{" "}
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

function DayCard({ day, spentAttr, spentFood, spentTotal, remaining, currency }: { day: PlanDay; spentAttr: number; spentFood: number; spentTotal: number; remaining: number; currency: string }) {
  const extras = day.extras ?? []; // tolerate plans from an older backend
  return (
    <Card>
      <h3 className="font-semibold text-zinc-900 dark:text-zinc-100">
        {day.weekday_name}{" "}
        <span className="ml-1 text-sm font-normal text-zinc-400 dark:text-zinc-500">
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
          <p className="text-sm text-zinc-400 dark:text-zinc-500">
            Free day — no bookable attractions were available.
          </p>
        )}
      </ol>
      {extras.length > 0 && (
        <div className="mt-4 rounded-xl bg-zinc-50 px-4 py-3 dark:bg-zinc-800/60">
          <p className="text-xs font-semibold uppercase tracking-wide text-zinc-400 dark:text-zinc-500">
            If you have time
          </p>
          <ul className="mt-2 flex flex-col gap-1.5">
            {extras.map((poi) => (
              <ExtraRow key={poi.id} poi={poi} />
            ))}
          </ul>
        </div>
      )}
      <div className="mt-4 flex flex-col gap-2 border-t border-zinc-100 pt-4 dark:border-zinc-800">
        <div className="flex items-center justify-between">
          <p className="text-sm text-zinc-500 dark:text-zinc-400">
            Estimated daily spend: <span className="font-semibold text-zinc-700 dark:text-zinc-300">{formatMoney(spentAttr, currency)}</span> (attractions) + <span className="font-semibold text-zinc-700 dark:text-zinc-300">{formatMoney(spentFood, currency)}</span> (food) = <span className="font-semibold text-zinc-700 dark:text-zinc-300">{formatMoney(spentTotal, currency)}</span>
          </p>
          <p className="text-sm text-zinc-500 dark:text-zinc-400">
            Budget remaining: <span className={`font-semibold ${remaining < 0 ? 'text-rose-600 dark:text-rose-400' : 'text-zinc-700 dark:text-zinc-300'}`}>{formatMoney(remaining, currency)}</span>
          </p>
        </div>
        <p className="text-xs text-zinc-400 dark:text-zinc-500">
          * Food prices are AI estimated averages for this city and may vary.
        </p>
      </div>
    </Card>
  );
}

function ExtraRow({ poi }: { poi: POI }) {
  return (
    <li className="flex items-center gap-2 text-sm">
      <span className="text-zinc-700 dark:text-zinc-300">{poi.name}</span>
      {poi.rating != null && (
        <span className="text-xs text-zinc-400 dark:text-zinc-500">
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
              : "bg-emerald-100 text-emerald-600 dark:bg-emerald-950 dark:text-emerald-400"
          }`}
        >
          {isMeal ? <ForkIcon /> : <PinIcon />}
        </span>
        {!isLast && <span className="w-px flex-1 bg-zinc-200 dark:bg-zinc-700" />}
      </div>
      <div className="pb-4">
        <p className="text-xs font-medium text-zinc-400 dark:text-zinc-500">
          {stop.arrive} – {stop.depart}
          {stop.travel_from_prev_minutes > 0 && (
            <span className="ml-2 text-zinc-300 dark:text-zinc-600">
              · {stop.travel_is_estimate ? "~" : ""}
              {stop.travel_from_prev_minutes}m travel
            </span>
          )}
        </p>
        <p className="flex flex-wrap items-center gap-2 font-medium text-zinc-800 dark:text-zinc-200">
          {stop.poi.name}
          {stop.meal && (
            <span className="rounded-full bg-amber-50 px-2 py-0.5 text-xs font-normal text-amber-600 dark:bg-amber-950 dark:text-amber-400">
              {stop.meal}
            </span>
          )}
          {stop.is_full_day && (
            <span className="rounded-full bg-violet-50 px-2 py-0.5 text-[10px] font-medium text-violet-600 dark:bg-violet-950/50 dark:text-violet-300">
              Full day
            </span>
          )}
          {stop.est_entry_cost &&
            (stop.est_entry_cost_source ? (
              <a
                href={stop.est_entry_cost_source}
                target="_blank"
                rel="noopener noreferrer"
                className="rounded-full bg-sky-50 px-2 py-0.5 text-[10px] font-normal text-sky-600 underline decoration-dotted underline-offset-2 hover:bg-sky-100 dark:bg-sky-950/50 dark:text-sky-400 dark:hover:bg-sky-900/50"
                title="Researched cost estimate — click to view the source. Please verify before you go."
              >
                {stop.est_entry_cost}
              </a>
            ) : (
              <span
                className="rounded-full bg-sky-50 px-2 py-0.5 text-[10px] font-normal text-sky-600 dark:bg-sky-950/50 dark:text-sky-400"
                title="Estimated cost. Could be wrong, please verify yourself."
              >
                {stop.est_entry_cost}
              </span>
            ))}
          {stop.poi.maps_url && <MapsLink href={stop.poi.maps_url} />}
        </p>
        {stop.poi.rating != null && (
          <p className="text-xs text-zinc-400 dark:text-zinc-500">
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
  return (
    <div className="mb-6 rounded-2xl border border-amber-200 bg-amber-50 px-5 py-4 dark:border-amber-900 dark:bg-amber-950/60">
      <p className="text-xs font-semibold uppercase tracking-wide text-amber-600 dark:text-amber-400">
        Heads up
      </p>
      <ul className="mt-1 flex flex-col gap-1 text-sm text-amber-800 dark:text-amber-200">
        <li>· Ticket and entry prices are AI estimates and may be outdated. Please verify them yourself.</li>
        {notes.map((n, i) => (
          <li key={i}>· {n.message}</li>
        ))}
      </ul>
    </div>
  );
}

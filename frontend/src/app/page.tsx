"use client";

import { useRouter } from "next/navigation";
import { FormEvent, useState } from "react";
import { createTrip } from "@/lib/api";

const INTEREST_OPTIONS = [
  "art",
  "history",
  "food",
  "nature",
  "architecture",
  "museums",
  "shopping",
  "nightlife",
];

function futureDate(daysFromNow: number): string {
  const d = new Date();
  d.setDate(d.getDate() + daysFromNow);
  return d.toISOString().slice(0, 10);
}

export default function HomePage() {
  const router = useRouter();
  const [origin, setOrigin] = useState("DEL");
  const [destination, setDestination] = useState("CDG");
  const [destinationCity, setDestinationCity] = useState("Paris");
  const [departureDate, setDepartureDate] = useState(futureDate(30));
  const [returnDate, setReturnDate] = useState(futureDate(35));
  const [budget, setBudget] = useState(250000);
  const [travelers, setTravelers] = useState(1);
  const [interests, setInterests] = useState<string[]>(["art", "history"]);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  function toggleInterest(tag: string) {
    setInterests((prev) =>
      prev.includes(tag) ? prev.filter((t) => t !== tag) : [...prev, tag],
    );
  }

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setSubmitting(true);
    setError(null);
    try {
      const tripId = await createTrip({
        origin: origin.trim().toUpperCase(),
        destination: destination.trim().toUpperCase(),
        destination_city: destinationCity.trim(),
        departure_date: departureDate,
        return_date: returnDate,
        budget,
        travelers,
        interests,
      });
      router.push(`/plan/${tripId}`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Something went wrong");
      setSubmitting(false);
    }
  }

  const inputClass =
    "w-full rounded-xl border border-zinc-200 bg-white px-4 py-2.5 text-zinc-900 shadow-sm outline-none transition focus:border-emerald-400 focus:ring-2 focus:ring-emerald-100 dark:border-zinc-700 dark:bg-zinc-900 dark:text-zinc-100 dark:focus:border-emerald-500 dark:focus:ring-emerald-950";
  const labelClass =
    "mb-1.5 block text-sm font-medium text-zinc-600 dark:text-zinc-400";

  return (
    <main className="flex flex-1 flex-col items-center px-4 py-12">
      <div className="w-full max-w-2xl">
        <header className="mb-10 text-center">
          <h1 className="text-4xl font-bold tracking-tight text-zinc-900 dark:text-zinc-100">
            Where To
          </h1>
          <p className="mx-auto mt-3 max-w-md text-zinc-500 dark:text-zinc-400">
            An AI travel agent that plans your whole trip from{" "}
            <span className="font-semibold text-zinc-700 dark:text-zinc-200">
              live data
            </span>{" "}
            — real flights, real hotels, real places. Nothing invented.
          </p>
        </header>

        <form
          onSubmit={onSubmit}
          className="rounded-3xl border border-zinc-200 bg-white p-6 shadow-xl shadow-zinc-200/50 sm:p-8 dark:border-zinc-800 dark:bg-zinc-900/80 dark:shadow-[0_0_40px_-12px_rgba(16,185,129,0.1)]"
        >
          <div className="grid grid-cols-1 gap-5 sm:grid-cols-2">
            <div>
              <label className={labelClass}>From (airport code)</label>
              <input
                className={inputClass}
                value={origin}
                onChange={(e) => setOrigin(e.target.value)}
                placeholder="DEL"
                maxLength={3}
                required
              />
            </div>
            <div>
              <label className={labelClass}>To (airport code)</label>
              <input
                className={inputClass}
                value={destination}
                onChange={(e) => setDestination(e.target.value)}
                placeholder="CDG"
                maxLength={3}
                required
              />
            </div>
            <div className="sm:col-span-2">
              <label className={labelClass}>Destination city</label>
              <input
                className={inputClass}
                value={destinationCity}
                onChange={(e) => setDestinationCity(e.target.value)}
                placeholder="Paris"
                required
              />
            </div>
            <div>
              <label className={labelClass}>Departure</label>
              <input
                type="date"
                className={inputClass}
                value={departureDate}
                onChange={(e) => setDepartureDate(e.target.value)}
                required
              />
            </div>
            <div>
              <label className={labelClass}>Return</label>
              <input
                type="date"
                className={inputClass}
                value={returnDate}
                min={departureDate}
                onChange={(e) => setReturnDate(e.target.value)}
                required
              />
            </div>
            <div>
              <label className={labelClass}>Total budget (INR)</label>
              <input
                type="number"
                className={inputClass}
                value={budget}
                min={1000}
                step={1000}
                onChange={(e) => setBudget(Number(e.target.value))}
                required
              />
            </div>
            <div>
              <label className={labelClass}>Travelers</label>
              <input
                type="number"
                className={inputClass}
                value={travelers}
                min={1}
                max={9}
                onChange={(e) => setTravelers(Number(e.target.value))}
                required
              />
            </div>
          </div>

          <div className="mt-6">
            <label className={labelClass}>Interests</label>
            <div className="flex flex-wrap gap-2">
              {INTEREST_OPTIONS.map((tag) => {
                const active = interests.includes(tag);
                return (
                  <button
                    key={tag}
                    type="button"
                    onClick={() => toggleInterest(tag)}
                    className={`rounded-full border px-4 py-1.5 text-sm font-medium transition ${
                      active
                        ? "border-emerald-500 bg-emerald-500 text-white shadow-sm"
                        : "border-zinc-200 bg-white text-zinc-600 hover:border-emerald-300 hover:text-emerald-600 dark:border-zinc-700 dark:bg-zinc-800 dark:text-zinc-300 dark:hover:border-emerald-600 dark:hover:text-emerald-400"
                    }`}
                  >
                    {tag}
                  </button>
                );
              })}
            </div>
          </div>

          {error && (
            <p className="mt-5 rounded-xl bg-rose-50 px-4 py-3 text-sm text-rose-600 dark:bg-rose-950/50 dark:text-rose-300">
              {error}
            </p>
          )}

          <button
            type="submit"
            disabled={submitting}
            className="mt-7 w-full rounded-xl bg-zinc-900 px-6 py-3.5 text-base font-semibold text-white shadow-lg transition hover:bg-zinc-700 disabled:cursor-not-allowed disabled:opacity-60 dark:bg-emerald-600 dark:hover:bg-emerald-500 dark:shadow-emerald-950/30"
          >
            {submitting ? "Handing off to your agent…" : "Plan my trip"}
          </button>
        </form>

        <p className="mt-6 text-center text-xs text-zinc-400 dark:text-zinc-500">
          Powered by live Google Flights, Hotels, Places &amp; Routes data —
          every price and place is real.
        </p>
      </div>
    </main>
  );
}

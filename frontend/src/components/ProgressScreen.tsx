"use client";

import { useEffect, useState } from "react";
import { StageEvent } from "@/lib/api";

const STAGE_FUN: Record<string, string[]> = {
  llm: ["Waking up your travel agent…", "Briefing the agent on your dream trip…"],
  flights: [
    "Scanning live flight prices…",
    "Comparing layovers and legroom…",
    "Racing through hundreds of fares…",
  ],
  flights_return: ["Matching return flights…", "Making sure you actually get home…"],
  hotels: ["Checking real hotel rates…", "Reading a few thousand reviews for you…"],
  attractions: [
    "Hunting down the good stuff…",
    "Shortlisting places worth your time…",
    "Rating sights by wow-factor…",
  ],
  finalize: ["Checking every fact against real data…", "No made-up prices allowed…"],
  restaurants: ["Scouting places to eat…", "Finding the best tables near your route…"],
  matrix: ["Timing the routes between stops…", "Studying the metro map…"],
  solving: [
    "Cooking up your itinerary…",
    "Solving the museum-traffic-lunch equation…",
    "Minimizing backtracking, maximizing wow…",
  ],
  assembling: ["Packing it all together…", "Putting the finishing touches on…"],
  done: ["Your trip is ready"],
  error: ["Something went sideways…"],
};

const CHECKLIST: { label: string; stages: string[] }[] = [
  { label: "Flights", stages: ["flights", "flights_return"] },
  { label: "Hotel", stages: ["hotels"] },
  { label: "Attractions", stages: ["attractions", "finalize"] },
  { label: "Food & routes", stages: ["restaurants", "matrix"] },
  { label: "Itinerary", stages: ["solving", "assembling", "done"] },
];

export default function ProgressScreen({ events }: { events: StageEvent[] }) {
  const current = events[events.length - 1];
  const stage = current?.stage ?? "llm";
  const fun = STAGE_FUN[stage] ?? STAGE_FUN.llm;
  const seenStages = new Set(events.map((e) => e.stage));

  const [funIndex, setFunIndex] = useState(0);
  useEffect(() => {
    setFunIndex(0);
    const timer = setInterval(() => setFunIndex((i) => i + 1), 2600);
    return () => clearInterval(timer);
  }, [stage]);

  const currentGroup = CHECKLIST.findIndex((g) => g.stages.includes(stage));

  return (
    <div className="flex w-full max-w-lg flex-col items-center text-center">
      <div className="relative flex h-20 w-20 items-center justify-center" aria-hidden>
        <span className="absolute inset-0 animate-spin rounded-full border-2 border-zinc-200 border-t-emerald-500 dark:border-zinc-700 dark:border-t-emerald-400 [animation-duration:1.4s]" />
        <span className="absolute inset-3 animate-spin rounded-full border-2 border-zinc-100 border-b-emerald-300 dark:border-zinc-800 dark:border-b-emerald-600 [animation-direction:reverse] [animation-duration:2.2s]" />
      </div>
      <p
        key={`${stage}-${funIndex % fun.length}`}
        className="animate-fade-slide mt-8 min-h-14 text-xl font-semibold text-zinc-800 dark:text-zinc-100"
      >
        {fun[funIndex % fun.length]}
      </p>
      <p className="mt-1 text-sm text-zinc-400 dark:text-zinc-500">
        Working with live data — this takes a moment
      </p>

      <ol className="mt-10 flex w-full flex-col gap-3 text-left">
        {CHECKLIST.map((group, i) => {
          const isDone =
            i < currentGroup ||
            group.stages.every((s) => seenStages.has(s)) ||
            seenStages.has("done");
          const isActive = i === currentGroup && !isDone;
          return (
            <li
              key={group.label}
              className={`flex items-center gap-3 rounded-xl border px-4 py-3 transition ${
                isDone
                  ? "border-emerald-200 bg-emerald-50 text-emerald-700 dark:border-emerald-900 dark:bg-emerald-950 dark:text-emerald-300"
                  : isActive
                    ? "border-emerald-200 bg-emerald-50/50 text-emerald-700 dark:border-emerald-800 dark:bg-emerald-950/50 dark:text-emerald-300"
                    : "border-zinc-200 bg-white text-zinc-400 dark:border-zinc-800 dark:bg-zinc-900 dark:text-zinc-600"
              }`}
            >
              <span className="flex h-5 w-5 items-center justify-center">
                {isDone ? <CheckIcon /> : isActive ? <Spinner /> : <DotIcon />}
              </span>
              <span className="font-medium">{group.label}</span>
            </li>
          );
        })}
      </ol>
    </div>
  );
}

function Spinner() {
  return (
    <span className="inline-block h-4 w-4 animate-spin rounded-full border-2 border-emerald-500 border-t-transparent" />
  );
}

function CheckIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
      <path d="M20 6 9 17l-5-5" />
    </svg>
  );
}

function DotIcon() {
  return <span className="h-1.5 w-1.5 rounded-full bg-current" />;
}

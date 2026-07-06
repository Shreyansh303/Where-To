"use client";

import { useEffect, useState } from "react";
import { StageEvent } from "@/lib/api";

const STAGE_META: Record<string, { emoji: string; fun: string[] }> = {
  llm: {
    emoji: "🤖",
    fun: ["Waking up your travel agent…", "Briefing the agent on your dream trip…"],
  },
  flights: {
    emoji: "✈️",
    fun: ["Scanning live flight prices…", "Comparing layovers and legroom…", "Racing through hundreds of fares…"],
  },
  flights_return: {
    emoji: "🛬",
    fun: ["Matching return flights…", "Making sure you actually get home…"],
  },
  hotels: {
    emoji: "🏨",
    fun: ["Haggling with hotels…", "Checking star ratings and pillow quality…"],
  },
  attractions: {
    emoji: "🗺️",
    fun: ["Hunting down the good stuff…", "Asking locals what's worth it…", "Rating museums by wow-factor…"],
  },
  finalize: {
    emoji: "🔍",
    fun: ["Checking every fact against real data…", "No made-up prices allowed…"],
  },
  restaurants: {
    emoji: "🍜",
    fun: ["Scouting places to eat…", "Sniffing out the best bistros…"],
  },
  matrix: {
    emoji: "🚇",
    fun: ["Timing the routes between stops…", "Studying the metro map…"],
  },
  solving: {
    emoji: "🍳",
    fun: ["Cooking up your itinerary…", "Solving the museum-traffic-lunch equation…", "Minimizing backtracking, maximizing wow…"],
  },
  assembling: {
    emoji: "📦",
    fun: ["Packing it all together…", "Printing your boarding pass (not really)…"],
  },
  done: { emoji: "🎉", fun: ["Your trip is ready!"] },
  error: { emoji: "😵", fun: ["Something went sideways…"] },
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
  const meta = STAGE_META[stage] ?? STAGE_META.llm;
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
      <div className="animate-float text-7xl" aria-hidden>
        {meta.emoji}
      </div>
      <p
        key={`${stage}-${funIndex % meta.fun.length}`}
        className="animate-fade-slide mt-6 min-h-14 text-xl font-semibold text-slate-800"
      >
        {meta.fun[funIndex % meta.fun.length]}
      </p>
      <p className="mt-1 text-sm text-slate-400">
        {current?.message && current.message !== meta.fun[funIndex % meta.fun.length]
          ? current.message
          : "Working with live data — this takes a moment"}
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
                  ? "border-emerald-200 bg-emerald-50 text-emerald-700"
                  : isActive
                    ? "border-sky-200 bg-sky-50 text-sky-700"
                    : "border-slate-200 bg-white text-slate-400"
              }`}
            >
              <span className="text-lg">
                {isDone ? "✅" : isActive ? <Spinner /> : "•"}
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
    <span className="inline-block h-4 w-4 animate-spin rounded-full border-2 border-sky-500 border-t-transparent align-middle" />
  );
}

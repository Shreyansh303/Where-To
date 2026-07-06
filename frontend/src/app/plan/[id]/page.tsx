"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import PlanView from "@/components/PlanView";
import ProgressScreen from "@/components/ProgressScreen";
import { StageEvent, TripPlan, eventsUrl, getTrip } from "@/lib/api";

type ViewState =
  | { phase: "connecting" }
  | { phase: "planning" }
  | { phase: "done"; plan: TripPlan }
  | { phase: "error"; message: string };

export default function PlanPage() {
  const { id } = useParams<{ id: string }>();
  const [events, setEvents] = useState<StageEvent[]>([]);
  const [state, setState] = useState<ViewState>({ phase: "connecting" });
  const finishedRef = useRef(false);

  useEffect(() => {
    if (!id) return;
    finishedRef.current = false;

    async function finish() {
      if (finishedRef.current) return;
      finishedRef.current = true;
      try {
        const status = await getTrip(id);
        if (status.status === "done" && status.plan) {
          setState({ phase: "done", plan: status.plan });
        } else {
          setState({
            phase: "error",
            message: status.error ?? "Planning failed for an unknown reason.",
          });
        }
      } catch (err) {
        setState({
          phase: "error",
          message: err instanceof Error ? err.message : "Unknown trip.",
        });
      }
    }

    const source = new EventSource(eventsUrl(id));
    source.onmessage = (msg) => {
      const event: StageEvent = JSON.parse(msg.data);
      if (event.stage === "end") {
        source.close();
        void finish();
        return;
      }
      setState((s) => (s.phase === "connecting" ? { phase: "planning" } : s));
      setEvents((prev) => [...prev, event]);
    };
    // SSE can fail (proxies, refreshes near completion) — fall back to polling.
    source.onerror = () => {
      source.close();
      const poll = setInterval(async () => {
        try {
          const status = await getTrip(id);
          if (status.status !== "running") {
            clearInterval(poll);
            void finish();
          }
        } catch {
          clearInterval(poll);
          void finish();
        }
      }, 1500);
    };
    return () => source.close();
  }, [id]);

  return (
    <main className="flex flex-1 flex-col items-center px-4 py-12">
      {(state.phase === "connecting" || state.phase === "planning") && (
        <ProgressScreen events={events} />
      )}

      {state.phase === "done" && (
        <>
          <PlanView plan={state.plan} />
          <BackLink label="Plan another trip" />
        </>
      )}

      {state.phase === "error" && (
        <div className="mt-16 w-full max-w-md rounded-3xl border border-rose-200 bg-white p-8 text-center shadow-lg">
          <p className="text-5xl">🧳💥</p>
          <h1 className="mt-4 text-xl font-bold text-slate-900">
            That trip hit turbulence
          </h1>
          <p className="mt-2 text-sm text-slate-500">{state.message}</p>
          <BackLink label="Try again" />
        </div>
      )}
    </main>
  );
}

function BackLink({ label }: { label: string }) {
  return (
    <Link
      href="/"
      className="mt-10 inline-block rounded-xl bg-slate-900 px-6 py-3 text-sm font-semibold text-white shadow transition hover:bg-slate-700"
    >
      ← {label}
    </Link>
  );
}

"use client";

/* Miles — the post-plan chat panel. Answers come from retrieval over this
   trip's own facts, so every reply carries the cards it was built from. */

import { useEffect, useRef, useState } from "react";
import { ChatMessage, Citation, sendChat } from "@/lib/api";

interface Turn extends ChatMessage {
  citations?: Citation[];
  degraded?: boolean;
}

const EMPTY_STATE =
  "Ask me anything about this trip — flights, days, prices, why something isn't included.";

export default function MilesChat({ tripId }: { tripId: string }) {
  const [open, setOpen] = useState(false);
  const [turns, setTurns] = useState<Turn[]>([]);
  const [draft, setDraft] = useState("");
  const [pending, setPending] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight });
  }, [turns, pending, open]);

  async function send() {
    const message = draft.trim();
    if (!message || pending) return;
    const history: ChatMessage[] = turns.map((t) => ({
      role: t.role,
      content: t.content,
    }));
    setTurns([...turns, { role: "user", content: message }]);
    setDraft("");
    setPending(true);
    try {
      const reply = await sendChat(tripId, message, history);
      setTurns((prev) => [
        ...prev,
        {
          role: "assistant",
          content: reply.answer,
          citations: reply.citations,
          degraded: reply.degraded,
        },
      ]);
    } catch (err) {
      setTurns((prev) => [
        ...prev,
        {
          role: "assistant",
          content:
            err instanceof Error ? err.message : "Miles couldn't answer that just now.",
          degraded: true,
        },
      ]);
    } finally {
      setPending(false);
    }
  }

  if (!open) {
    return (
      <button
        type="button"
        onClick={() => setOpen(true)}
        aria-label="Ask Miles about this trip"
        className="fixed bottom-6 right-6 z-50 flex items-center gap-2 rounded-full bg-emerald-600 px-5 py-3 text-sm font-semibold text-white shadow-lg transition hover:bg-emerald-500"
      >
        <ChatIcon />
        Ask Miles
      </button>
    );
  }

  return (
    <div className="fixed bottom-6 right-6 z-50 flex h-[min(32rem,80vh)] w-[min(24rem,calc(100vw-3rem))] flex-col overflow-hidden rounded-2xl border border-zinc-200 bg-white shadow-2xl dark:border-zinc-800 dark:bg-zinc-900">
      <header className="flex items-center justify-between border-b border-zinc-100 px-4 py-3 dark:border-zinc-800">
        <div>
          <p className="text-sm font-semibold text-zinc-900 dark:text-zinc-100">Miles</p>
          <p className="text-[11px] text-zinc-400 dark:text-zinc-500">
            Answers from your plan only
          </p>
        </div>
        <button
          type="button"
          onClick={() => setOpen(false)}
          aria-label="Close chat"
          className="rounded-lg p-1.5 text-zinc-400 transition hover:bg-zinc-100 hover:text-zinc-600 dark:hover:bg-zinc-800 dark:hover:text-zinc-300"
        >
          <CloseIcon />
        </button>
      </header>

      <div ref={scrollRef} className="flex-1 overflow-y-auto px-4 py-4">
        {turns.length === 0 && (
          <p className="rounded-2xl bg-emerald-50 px-4 py-3 text-sm leading-relaxed text-emerald-900 dark:bg-emerald-950/50 dark:text-emerald-200">
            {EMPTY_STATE}
          </p>
        )}
        <div className="flex flex-col gap-4">
          {turns.map((turn, i) => (
            <Bubble key={i} turn={turn} />
          ))}
          {pending && (
            <p className="text-sm italic text-zinc-400 dark:text-zinc-500">
              Miles is thinking…
            </p>
          )}
        </div>
      </div>

      <div className="border-t border-zinc-100 p-3 dark:border-zinc-800">
        <textarea
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              void send();
            }
          }}
          rows={2}
          placeholder="Ask about your trip…"
          className="w-full resize-none rounded-xl border border-zinc-200 bg-zinc-50 px-3 py-2 text-sm text-zinc-800 outline-none transition placeholder:text-zinc-400 focus:border-emerald-400 dark:border-zinc-700 dark:bg-zinc-800 dark:text-zinc-100 dark:placeholder:text-zinc-500 dark:focus:border-emerald-600"
        />
        <div className="mt-2 flex items-center justify-between">
          <span className="text-[11px] text-zinc-400 dark:text-zinc-500">
            Enter to send
          </span>
          <button
            type="button"
            onClick={() => void send()}
            disabled={pending || draft.trim().length === 0}
            className="rounded-lg bg-zinc-900 px-4 py-1.5 text-xs font-semibold text-white transition hover:bg-zinc-700 disabled:opacity-40 dark:bg-emerald-600 dark:hover:bg-emerald-500"
          >
            Send
          </button>
        </div>
      </div>
    </div>
  );
}

function Bubble({ turn }: { turn: Turn }) {
  if (turn.role === "user") {
    return (
      <p className="ml-auto max-w-[85%] rounded-2xl rounded-br-sm bg-zinc-900 px-3.5 py-2 text-sm text-white dark:bg-emerald-700">
        {turn.content}
      </p>
    );
  }
  return (
    <div className="max-w-[92%]">
      <p className="whitespace-pre-wrap rounded-2xl rounded-bl-sm bg-zinc-100 px-3.5 py-2 text-sm leading-relaxed text-zinc-800 dark:bg-zinc-800 dark:text-zinc-200">
        {turn.content}
      </p>
      {turn.citations && turn.citations.length > 0 && (
        <div className="mt-2 flex flex-wrap gap-1.5">
          {turn.citations.map((c, i) => (
            <CitationChip key={c.chunk_id} index={i + 1} citation={c} />
          ))}
        </div>
      )}
      {turn.degraded && (
        <p className="mt-2 rounded-xl border border-amber-200 bg-amber-50 px-3 py-2 text-[11px] leading-relaxed text-amber-800 dark:border-amber-900 dark:bg-amber-950/60 dark:text-amber-200">
          Miles is running in reduced mode right now — this answer comes straight from
          your plan, unpolished.
        </p>
      )}
    </div>
  );
}

/* Mirrors the price-source chips in PlanView: sourced facts link out. */
function CitationChip({ index, citation }: { index: number; citation: Citation }) {
  const label = `[${index}] ${citation.label}`;
  const className =
    "rounded-full bg-sky-50 px-2 py-0.5 text-[10px] font-normal text-sky-600 dark:bg-sky-950/50 dark:text-sky-400";
  if (citation.source_url) {
    return (
      <a
        href={citation.source_url}
        target="_blank"
        rel="noopener noreferrer"
        title="Open the source behind this fact"
        className={`${className} underline decoration-dotted underline-offset-2 hover:bg-sky-100 dark:hover:bg-sky-900/50`}
      >
        {label}
      </a>
    );
  }
  return (
    <span className={className} title="From your plan">
      {label}
    </span>
  );
}

function ChatIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M21 11.5a8.4 8.4 0 0 1-9 8.4 8.9 8.9 0 0 1-4-.9L3 21l1.9-5a8.4 8.4 0 0 1-.9-3.9 8.4 8.4 0 0 1 8.5-8.4 8.4 8.4 0 0 1 8.5 8.3z" />
    </svg>
  );
}

function CloseIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M18 6 6 18M6 6l12 12" />
    </svg>
  );
}

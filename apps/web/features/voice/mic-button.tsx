"use client";

import { useQuery } from "@tanstack/react-query";
import { useLocale, useTranslations } from "next-intl";
import Link from "next/link";
import { useEffect, useRef, useState, useSyncExternalStore } from "react";

import { Info, Loader2, Mic, Square, X } from "@/components/icons";
import { Button } from "@/components/ui/button";
import { useErrorMessage } from "@/features/auth/use-error-message";
import { transcribeAudio } from "@/lib/api/chat";
import { getAiServices, searchKeys } from "@/lib/api/search";
import { cn } from "@/lib/utils";

const MAX_SECONDS = 120;
const TYPES = ["audio/webm;codecs=opus", "audio/webm", "audio/mp4", "audio/ogg;codecs=opus"];

const noop = () => () => {};
const supported = () =>
  typeof window !== "undefined" && !!navigator.mediaDevices?.getUserMedia && typeof MediaRecorder !== "undefined";

/** Recorder format the browser can make (Safari: mp4, Chrome/Firefox: webm/ogg). */
export function pickType(isSupported: (type: string) => boolean): string | undefined {
  return TYPES.find((type) => isSupported(type));
}

export function extensionFor(type: string): string {
  if (type.includes("mp4")) return "m4a";
  if (type.includes("ogg")) return "ogg";
  return "webm";
}

/**
 * Voice input: press to record, press again (or wait 2 minutes) to stop; the speech is
 * turned into text by the owner's provider and handed to `onText`. Without a provider for it,
 * a press explains how to get one (before anything is recorded) instead of failing afterwards.
 */
export function MicButton({ onText, className, disabled }: { onText: (text: string) => void; className?: string; disabled?: boolean }) {
  const t = useTranslations("voice");
  const locale = useLocale();
  const toMessage = useErrorMessage();
  const canRecord = useSyncExternalStore(noop, supported, () => false);
  const [state, setState] = useState<"idle" | "recording" | "sending">("idle");
  const [seconds, setSeconds] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [needsSetup, setNeedsSetup] = useState(false);
  const ai = useQuery({ queryKey: searchKeys.ai, queryFn: ({ signal }) => getAiServices(signal), staleTime: 60_000 });
  const unavailable = ai.data?.available === false;
  const recorder = useRef<MediaRecorder | null>(null);
  const timer = useRef<number>(0);
  const mounted = useRef(true);

  useEffect(() => {
    mounted.current = true;
    return () => {
      // Closed mid-recording (e.g. Escape on a dialog): stop the mic and send nothing — a
      // transcription nobody will see would still be a paid call.
      mounted.current = false;
      window.clearInterval(timer.current);
      recorder.current?.stream.getTracks().forEach((track) => track.stop());
    };
  }, []);

  if (!canRecord) return null;

  async function start() {
    setError(null);
    if (unavailable) {
      setNeedsSetup(true);
      return;
    }
    let stream: MediaStream;
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    } catch {
      setError(t("denied"));
      return;
    }
    const type = pickType((x) => MediaRecorder.isTypeSupported(x));
    const rec = new MediaRecorder(stream, type ? { mimeType: type } : undefined);
    const chunks: Blob[] = [];
    rec.ondataavailable = (e) => e.data.size > 0 && chunks.push(e.data);
    rec.onstop = async () => {
      window.clearInterval(timer.current);
      stream.getTracks().forEach((track) => track.stop());
      if (!mounted.current) return;
      const mime = rec.mimeType || type || "audio/webm";
      const blob = new Blob(chunks, { type: mime });
      if (blob.size === 0) {
        setState("idle");
        return;
      }
      setState("sending");
      try {
        const { text } = await transcribeAudio(blob, `voice.${extensionFor(mime)}`, locale);
        if (text) onText(text);
        else setError(t("nothing"));
      } catch (e) {
        setError(toMessage(e).message);
      } finally {
        setState("idle");
      }
    };
    recorder.current = rec;
    rec.start();
    setSeconds(0);
    setState("recording");
    const began = Date.now();
    timer.current = window.setInterval(() => {
      const s = Math.floor((Date.now() - began) / 1000);
      setSeconds(s);
      if (s >= MAX_SECONDS && rec.state === "recording") rec.stop();
    }, 250);
  }

  function stop() {
    if (recorder.current?.state === "recording") recorder.current.stop();
  }

  const recording = state === "recording";
  return (
    <span className={cn("relative inline-flex items-center", className)}>
      <Button
        type="button"
        size="icon"
        variant={recording ? "destructive" : "ghost"}
        className=""
        disabled={disabled || state === "sending"}
        aria-pressed={recording}
        aria-label={recording ? t("stop") : t("start")}
        title={recording ? t("stop") : unavailable ? t("needsProvider") : t("start")}
        onClick={() => (recording ? stop() : void start())}
        data-testid="mic"
      >
        {state === "sending" ? <Loader2 className="animate-spin" /> : recording ? <Square /> : <Mic />}
      </Button>
      {recording && (
        <span className="absolute -top-5 left-1/2 -translate-x-1/2 bg-destructive px-1 text-xs text-white tabular-nums" aria-hidden>
          ● {Math.floor(seconds / 60)}:{String(seconds % 60).padStart(2, "0")}
        </span>
      )}
      {(error || needsSetup) && !recording && (
        // Visible, not only a tooltip: phones have no hover.
        <span
          role="alert"
          className="absolute right-0 bottom-full z-20 mb-2 flex w-72 max-w-[calc(100vw-2rem)] items-start gap-2 bg-card p-3 text-left text-xs text-card-foreground pixel-frame"
        >
          <Info className="mt-0.5 size-4 shrink-0 text-sky" aria-hidden />
          <span className="flex min-w-0 flex-1 flex-col items-start gap-1.5">
            <span>{needsSetup ? t("needsProvider") : error}</span>
            {needsSetup && (
              <Link href="/settings#ai" className="font-medium text-sky underline-offset-2 hover:underline">
                {t("openSettings")}
              </Link>
            )}
          </span>
          <button
            type="button"
            aria-label={t("closeHint")}
            className="-m-1.5 flex size-7 shrink-0 items-center justify-center text-muted-foreground hover:text-foreground"
            onClick={() => {
              setError(null);
              setNeedsSetup(false);
            }}
          >
            <X className="size-3.5" />
          </button>
        </span>
      )}
    </span>
  );
}

"use client";

import { useQuery } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import Link from "next/link";
import { useEffect, useRef, useState, useSyncExternalStore } from "react";

import { Check, Info, Loader2, Mic, X } from "@/components/icons";
import { Button } from "@/components/ui/button";
import { useErrorMessage } from "@/features/auth/use-error-message";
import { transcribeAudio } from "@/lib/api/chat";
import { getAiServices, searchKeys } from "@/lib/api/search";
import { cn } from "@/lib/utils";

const MAX_SECONDS = 15 * 60; // long dictations are fine; the speech engine has no short cap
const TYPES = ["audio/webm;codecs=opus", "audio/webm", "audio/mp4", "audio/ogg;codecs=opus"];
const BARS = 12;
/** Recognition language: auto-detect (the owner speaks Russian and English), or one of them. */
const LANGS = ["auto", "ru", "en"] as const;
type Lang = (typeof LANGS)[number];
const LANG_KEY = "moloko.voice.lang";

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

/** "1:05" */
export function clock(seconds: number): string {
  return `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, "0")}`;
}

function loadLang(): Lang {
  try {
    const value = localStorage.getItem(LANG_KEY);
    return LANGS.includes(value as Lang) ? (value as Lang) : "auto";
  } catch {
    return "auto";
  }
}

/**
 * Voice input. A press starts recording and the button becomes a recording strip: a timer, a
 * live level meter, «Отменить» (throw the recording away, also Escape) and «Готово» (turn the
 * speech into text — local Whisper or the owner's provider — and hand it to `onText`). Without
 * any speech engine a press explains how to get one, before anything is recorded.
 */
export function MicButton({ onText, className, disabled }: { onText: (text: string) => void; className?: string; disabled?: boolean }) {
  const t = useTranslations("voice");
  const toMessage = useErrorMessage();
  const canRecord = useSyncExternalStore(noop, supported, () => false);
  const [state, setState] = useState<"idle" | "recording" | "sending">("idle");
  const [seconds, setSeconds] = useState(0);
  const [levels, setLevels] = useState<number[]>(() => Array(BARS).fill(0));
  // Only shown while recording (client side), so reading storage here never mismatches the server HTML.
  const [lang, setLang] = useState<Lang>(loadLang);
  const [error, setError] = useState<string | null>(null);
  const [needsSetup, setNeedsSetup] = useState(false);
  const ai = useQuery({ queryKey: searchKeys.ai, queryFn: ({ signal }) => getAiServices(signal), staleTime: 60_000 });
  // `voice_available` (local speech engine or a provider) when the server reports it; older servers: `available`.
  const voice = ai.data as { voice_available?: boolean; available?: boolean } | undefined;
  const unavailable = voice ? (voice.voice_available ?? voice.available) === false : false;
  const recorder = useRef<MediaRecorder | null>(null);
  const discard = useRef(false);
  const timer = useRef<number>(0);
  const frame = useRef<number>(0);
  const audio = useRef<AudioContext | null>(null);
  const mounted = useRef(true);

  useEffect(() => {
    mounted.current = true;
    return () => {
      // Closed mid-recording (e.g. Escape on a dialog): stop the mic and send nothing — a
      // transcription nobody will see would still be work for nothing.
      mounted.current = false;
      stopMeter();
      recorder.current?.stream.getTracks().forEach((track) => track.stop());
    };
  }, []);

  // Escape while recording = cancel (and it does not close a surrounding dialog).
  const cancelRef = useRef<() => void>(() => {});
  useEffect(() => {
    if (state !== "recording") return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== "Escape") return;
      e.preventDefault();
      e.stopPropagation();
      cancelRef.current();
    };
    window.addEventListener("keydown", onKey, true);
    return () => window.removeEventListener("keydown", onKey, true);
  }, [state]);

  if (!canRecord) return null;

  function stopMeter() {
    window.clearInterval(timer.current);
    cancelAnimationFrame(frame.current);
    void audio.current?.close().catch(() => undefined);
    audio.current = null;
  }

  /** A live level meter from the microphone (12 bars, about 15 updates a second). */
  function startMeter(stream: MediaStream) {
    try {
      const context = new AudioContext();
      const analyser = context.createAnalyser();
      analyser.fftSize = 256;
      context.createMediaStreamSource(stream).connect(analyser);
      audio.current = context;
      const data = new Uint8Array(analyser.fftSize);
      let last = 0;
      const tick = (time: number) => {
        frame.current = requestAnimationFrame(tick);
        if (time - last < 66) return;
        last = time;
        analyser.getByteTimeDomainData(data);
        let sum = 0;
        for (const v of data) sum += ((v - 128) / 128) ** 2;
        const level = Math.min(1, Math.sqrt(sum / data.length) * 4);
        setLevels((prev) => [...prev.slice(1), level]);
      };
      frame.current = requestAnimationFrame(tick);
    } catch {
      // no Web Audio: recording still works, just without the meter
    }
  }

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
    discard.current = false;
    rec.ondataavailable = (e) => e.data.size > 0 && chunks.push(e.data);
    rec.onstop = async () => {
      stopMeter();
      stream.getTracks().forEach((track) => track.stop());
      if (!mounted.current) return;
      const mime = rec.mimeType || type || "audio/webm";
      const blob = new Blob(chunks, { type: mime });
      if (discard.current || blob.size === 0) {
        setState("idle");
        return;
      }
      setState("sending");
      try {
        const { text } = await transcribeAudio(blob, `voice.${extensionFor(mime)}`, lang === "auto" ? "" : lang);
        if (text) onText(text);
        else setError(t("nothing"));
      } catch (e) {
        setError(toMessage(e).message);
      } finally {
        if (mounted.current) setState("idle");
      }
    };
    recorder.current = rec;
    rec.start(1000);
    setSeconds(0);
    setLevels(Array(BARS).fill(0));
    setState("recording");
    startMeter(stream);
    const began = Date.now();
    timer.current = window.setInterval(() => {
      const s = Math.floor((Date.now() - began) / 1000);
      setSeconds(s);
      if (s >= MAX_SECONDS && rec.state === "recording") rec.stop();
    }, 250);
  }

  function finish() {
    if (recorder.current?.state === "recording") recorder.current.stop();
  }

  function cancel() {
    discard.current = true;
    finish();
  }
  cancelRef.current = cancel;

  function nextLang() {
    const next = LANGS[(LANGS.indexOf(lang) + 1) % LANGS.length]!;
    setLang(next);
    try {
      localStorage.setItem(LANG_KEY, next);
    } catch {
      // private mode: the choice lasts for this page only
    }
  }

  if (state === "recording") {
    return (
      <span
        role="group"
        aria-label={t("recording")}
        className={cn("inline-flex h-10 shrink-0 items-center gap-2 bg-card pr-1 pl-3 pixel-frame [--frame-color:var(--color-destructive)]", className)}
        data-testid="mic-recording"
      >
        <span aria-hidden className="size-2.5 animate-pulse bg-destructive" />
        <span className="font-mono text-xs tabular-nums" aria-live="off">
          {clock(seconds)}
        </span>
        <span aria-hidden className="flex h-6 items-end gap-[3px]">
          {levels.map((level, i) => (
            <span key={i} className="w-[3px] bg-destructive" style={{ height: `${Math.max(3, Math.round(level * 8) * 3)}px` }} />
          ))}
        </span>
        <button
          type="button"
          onClick={nextLang}
          title={t("language")}
          aria-label={`${t("language")}: ${t(`langs.${lang}`)}`}
          className="h-8 px-1.5 text-xs text-muted-foreground hover:text-foreground"
        >
          {t(`langs.${lang}`)}
        </button>
        <Button type="button" size="icon" variant="ghost" className="size-8" aria-label={t("cancel")} title={t("cancel")} onClick={cancel}>
          <X />
        </Button>
        <Button type="button" size="icon" variant="ghost" className="size-8 text-grass" aria-label={t("done")} title={t("done")} onClick={finish}>
          <Check />
        </Button>
      </span>
    );
  }

  return (
    <span className={cn("relative inline-flex items-center", className)}>
      <Button
        type="button"
        size="icon"
        variant="ghost"
        disabled={disabled || state === "sending"}
        aria-label={state === "sending" ? t("transcribing") : t("start")}
        title={state === "sending" ? t("transcribing") : unavailable ? t("needsProvider") : t("start")}
        onClick={() => void start()}
        data-testid="mic"
      >
        {state === "sending" ? <Loader2 className="animate-spin" /> : <Mic />}
      </Button>
      {(error || needsSetup) && (
        // Visible, not only a tooltip: phones have no hover.
        <span
          role="alert"
          className="absolute right-0 bottom-full z-20 mb-2 flex w-72 max-w-[calc(100vw-2rem)] items-start gap-2 bg-card p-3 text-left text-xs text-card-foreground pixel-frame shadow-md"
        >
          <Info className="mt-0.5 shrink-0 text-sky" aria-hidden />
          <span className="flex min-w-0 flex-1 flex-col items-start gap-1.5">
            <span>{needsSetup ? t("needsProvider") : error}</span>
            {needsSetup && (
              <Link href="/settings/ai" className="text-sky underline-offset-2 hover:underline">
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
            <X className="size-3" />
          </button>
        </span>
      )}
    </span>
  );
}

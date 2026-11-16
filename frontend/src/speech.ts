// Browser speech: Web Speech API recognition (Chrome / Edge) and speech synthesis (all modern browsers).
// Audio never reaches MockMate's server; only the text transcript is sent (SRS 6.1).
import { useCallback, useEffect, useRef, useState } from "react";

// ---- minimal typings (SpeechRecognition is not in TypeScript's DOM lib) ----
type RecognitionAlternative = { transcript: string };
type RecognitionResult = { isFinal: boolean; 0: RecognitionAlternative; length: number };
type RecognitionEvent = { resultIndex: number; results: { length: number; [i: number]: RecognitionResult } };
type RecognitionErrorEvent = { error: string };
interface Recognition {
  lang: string;
  continuous: boolean;
  interimResults: boolean;
  onresult: ((e: RecognitionEvent) => void) | null;
  onerror: ((e: RecognitionErrorEvent) => void) | null;
  onend: (() => void) | null;
  start(): void;
  stop(): void;
  abort(): void;
}
type RecognitionCtor = new () => Recognition;

function recognitionCtor(): RecognitionCtor | null {
  const w = window as unknown as { SpeechRecognition?: RecognitionCtor; webkitSpeechRecognition?: RecognitionCtor };
  return w.SpeechRecognition ?? w.webkitSpeechRecognition ?? null;
}

export const speechInputSupported = () => typeof window !== "undefined" && recognitionCtor() !== null;
export const speechOutputSupported = () => typeof window !== "undefined" && "speechSynthesis" in window;

const ERRORS: Record<string, string> = {
  "not-allowed": "Microphone access is blocked. Allow it in your browser's site settings, or answer by text.",
  "service-not-allowed": "Speech recognition is not allowed in this browser. Please answer by text.",
  "audio-capture": "No microphone was found. Check your microphone, or answer by text.",
  network: "Speech recognition needs an internet connection. Please answer by text for now.",
};

export type VoiceResult = { transcript: string; seconds: number | null };

/** Continuous dictation. `transcript` is final text so far; `interim` is the words still being recognised. */
export function useSpeechRecognition(lang = "en-US") {
  const [listening, setListening] = useState(false);
  const [transcript, setTranscript] = useState("");
  const [interim, setInterim] = useState("");
  const [error, setError] = useState<string | null>(null);
  const recRef = useRef<Recognition | null>(null);
  const wantRef = useRef(false); // Chrome stops after a pause; restart while the user still wants to talk
  const finalRef = useRef("");
  const speakingMs = useRef(0);
  const segStart = useRef<number | null>(null);
  const segLast = useRef<number | null>(null);

  const closeSegment = () => {
    if (segStart.current !== null && segLast.current !== null) {
      // first-to-last result in a segment approximates time spent speaking, excluding the initial pause
      speakingMs.current += Math.max(segLast.current - segStart.current, 0) + 400;
    }
    segStart.current = null;
    segLast.current = null;
  };

  const start = useCallback(() => {
    const Ctor = recognitionCtor();
    if (!Ctor || wantRef.current) return;
    setError(null);
    const rec = new Ctor();
    rec.lang = lang;
    rec.continuous = true;
    rec.interimResults = true;
    rec.onresult = (e) => {
      const now = performance.now();
      if (segStart.current === null) segStart.current = now;
      segLast.current = now;
      let pending = "";
      for (let i = e.resultIndex; i < e.results.length; i++) {
        const text = e.results[i][0].transcript;
        if (e.results[i].isFinal) finalRef.current = `${finalRef.current} ${text}`.replace(/\s+/g, " ").trim();
        else pending += text;
      }
      setTranscript(finalRef.current);
      setInterim(pending.trim());
    };
    rec.onerror = (e) => {
      if (e.error === "no-speech" || e.error === "aborted") return;
      setError(ERRORS[e.error] ?? "Speech recognition stopped unexpectedly. You can try again or type.");
      wantRef.current = false;
    };
    rec.onend = () => {
      closeSegment();
      setInterim("");
      if (wantRef.current) {
        try {
          rec.start();
          return;
        } catch {
          wantRef.current = false;
        }
      }
      setListening(false);
    };
    recRef.current = rec;
    wantRef.current = true;
    try {
      rec.start();
      setListening(true);
    } catch {
      wantRef.current = false;
      setError("Could not start the microphone. Please try again.");
    }
  }, [lang]);

  const stop = useCallback(() => {
    wantRef.current = false;
    recRef.current?.stop();
  }, []);

  /** Clear everything for the next answer and return what was captured. */
  const reset = useCallback((): VoiceResult => {
    wantRef.current = false;
    recRef.current?.abort();
    closeSegment();
    const result = { transcript: finalRef.current, seconds: speakingMs.current ? speakingMs.current / 1000 : null };
    finalRef.current = "";
    speakingMs.current = 0;
    setTranscript("");
    setInterim("");
    return result;
  }, []);

  /** Speaking time and raw transcript so far, without clearing. */
  const peek = useCallback(
    (): VoiceResult => ({
      transcript: finalRef.current,
      seconds: speakingMs.current ? speakingMs.current / 1000 : null,
    }),
    [],
  );

  useEffect(
    () => () => {
      wantRef.current = false;
      recRef.current?.abort();
    },
    [],
  );

  return { supported: speechInputSupported(), listening, transcript, interim, error, start, stop, reset, peek };
}

/** Text-to-speech for interviewer questions, preferring an English voice. */
export function useSpeechSynthesis() {
  const supported = speechOutputSupported();
  const [speaking, setSpeaking] = useState(false);
  const voiceRef = useRef<SpeechSynthesisVoice | null>(null);

  useEffect(() => {
    if (!supported) return;
    const pick = () => {
      const voices = window.speechSynthesis.getVoices();
      voiceRef.current =
        voices.find((v) => v.lang === "en-US" && v.localService) ??
        voices.find((v) => v.lang.startsWith("en")) ??
        null;
    };
    pick();
    window.speechSynthesis.addEventListener("voiceschanged", pick);
    return () => {
      window.speechSynthesis.removeEventListener("voiceschanged", pick);
      window.speechSynthesis.cancel();
    };
  }, [supported]);

  const cancel = useCallback(() => {
    if (!supported) return;
    window.speechSynthesis.cancel();
    setSpeaking(false);
  }, [supported]);

  const speak = useCallback(
    (text: string) => {
      if (!supported) return;
      window.speechSynthesis.cancel();
      const u = new SpeechSynthesisUtterance(text);
      if (voiceRef.current) u.voice = voiceRef.current;
      u.lang = voiceRef.current?.lang ?? "en-US";
      u.rate = 1;
      u.onstart = () => setSpeaking(true);
      u.onend = () => setSpeaking(false);
      u.onerror = () => setSpeaking(false);
      window.speechSynthesis.speak(u);
    },
    [supported],
  );

  return { supported, speaking, speak, cancel };
}

// ---- small persisted preferences (per browser) ----
export function readPref<T extends string>(key: string, fallback: T): T {
  try {
    return (localStorage.getItem(`mockmate.${key}`) as T | null) ?? fallback;
  } catch {
    return fallback;
  }
}

export function writePref(key: string, value: string) {
  try {
    localStorage.setItem(`mockmate.${key}`, value);
  } catch {
    /* storage unavailable: preference lasts for this page only */
  }
}

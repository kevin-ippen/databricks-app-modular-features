/**
 * useVoiceConversation Hook
 *
 * Orchestrates the full voice conversation loop:
 *   IDLE -> LISTENING -> TRANSCRIBING -> STREAMING -> SPEAKING -> LISTENING -> ...
 *
 * Composes existing ASR, chat streaming (SSE), and TTS endpoints
 * into a real-time conversational experience. No new backend endpoints required.
 *
 * Integration with useChat:
 *   This hook provides `onTextDelta` and `onStreamComplete` callbacks that
 *   should be passed into useChat's options. The voice hook uses onTextDelta
 *   to accumulate text and fire sentence-level TTS calls during the stream.
 *
 * All endpoints and parameters are configurable via the options object.
 */

import { useState, useRef, useCallback, useEffect } from "react";
import {
  audioBufferToWav,
  stripMarkdown,
  detectSentenceBoundaries,
  computeVolumeLevel,
} from "./audioUtils";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export type VoiceState =
  | "idle"
  | "listening"
  | "transcribing"
  | "streaming"
  | "speaking";

export interface UseVoiceConversationOptions {
  /** Endpoint for ASR transcription. Required. */
  transcribeEndpoint: string;
  /** Endpoint for TTS synthesis. Required. */
  synthesizeEndpoint: string;
  /** TTS speaker voice. Default: Ryan */
  speaker?: string;
  /** TTS audience mode. Default: exec */
  audienceMode?: string;
  /** Audio playback speed multiplier. Default: 1.25 */
  playbackRate?: number;
  /** VAD speech threshold (0-255). Default: 30 */
  speechThreshold?: number;
  /** VAD silence duration before auto-stop (ms). Default: 1500 */
  silenceDurationMs?: number;
  /** Conversational filler phrases for bridging TTS latency. */
  fillerPhrases?: string[];
  /** Send a message through the chat system. Provided by parent component. */
  sendMessage?: (text: string) => Promise<void>;
  /** Cancel the current stream. Provided by parent component. */
  cancelStream?: () => void;
}

export interface UseVoiceConversationReturn {
  state: VoiceState;
  transcript: string;
  agentText: string;
  volumeLevel: number;
  isActive: boolean;
  start: () => void;
  stop: () => void;
  interrupt: () => void;
  /** Pass this to useChat options.onTextDelta */
  onTextDelta: (delta: string, accumulated: string) => void;
  /** Pass this to useChat options.onStreamComplete */
  onStreamComplete: (fullText: string) => void;
}

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const VAD_POLL_INTERVAL_MS = 100;
const ASR_SAMPLE_RATE = 16000;

const DEFAULT_FILLER_PHRASES = [
  "Hmm, let me look into that.",
  "Sure, let me think on that for a moment.",
  "That's a great question, one second.",
  "Let me pull that up for you.",
  "Good question, let me check.",
];

// Module-level cache for pre-generated filler audio blobs
const fillerCache: Map<string, Blob> = new Map();
let fillerWarmupDone = false;

// ---------------------------------------------------------------------------
// Hook
// ---------------------------------------------------------------------------

export function useVoiceConversation(
  options: UseVoiceConversationOptions
): UseVoiceConversationReturn {
  const {
    transcribeEndpoint,
    synthesizeEndpoint,
    speaker = "Ryan",
    audienceMode = "exec",
    playbackRate = 1.25,
    speechThreshold = 30,
    silenceDurationMs = 1500,
    fillerPhrases = DEFAULT_FILLER_PHRASES,
    sendMessage,
    cancelStream,
  } = options;

  // -- State --
  const [state, setState] = useState<VoiceState>("idle");
  const [transcript, setTranscript] = useState("");
  const [agentText, setAgentText] = useState("");
  const [volumeLevel, setVolumeLevel] = useState(0);

  // -- Refs --
  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  const audioChunksRef = useRef<Blob[]>([]);
  const streamRef = useRef<MediaStream | null>(null);
  const audioContextRef = useRef<AudioContext | null>(null);
  const analyserRef = useRef<AnalyserNode | null>(null);
  const vadIntervalRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const speechDetectedRef = useRef(false);
  const silenceStartRef = useRef<number | null>(null);

  // TTS audio queue
  const audioQueueRef = useRef<Promise<Blob | null>[]>([]);
  const isPlayingRef = useRef(false);
  const currentAudioRef = useRef<HTMLAudioElement | null>(null);
  const playbackAbortRef = useRef(false);

  // Sentence detection state for streaming TTS
  const sentenceBufferRef = useRef("");
  const firedSentencesRef = useRef<string[]>([]);

  const isActiveRef = useRef(false);
  const fillerPlayedRef = useRef(false);

  // -- Helpers --

  const cleanupMic = useCallback(() => {
    if (vadIntervalRef.current) {
      clearInterval(vadIntervalRef.current);
      vadIntervalRef.current = null;
    }
    if (mediaRecorderRef.current?.state !== "inactive") {
      mediaRecorderRef.current?.stop();
    }
    streamRef.current?.getTracks().forEach((t) => t.stop());
    streamRef.current = null;
    audioContextRef.current?.close();
    audioContextRef.current = null;
    analyserRef.current = null;
    speechDetectedRef.current = false;
    silenceStartRef.current = null;
  }, []);

  const stopPlayback = useCallback(() => {
    playbackAbortRef.current = true;
    if (currentAudioRef.current) {
      currentAudioRef.current.pause();
      currentAudioRef.current = null;
    }
    audioQueueRef.current = [];
    isPlayingRef.current = false;
  }, []);

  // -- Filler warmup --

  const warmupFillers = useCallback(async () => {
    if (fillerWarmupDone) return;
    fillerWarmupDone = true;
    console.log("[VoiceConversation] Pre-generating filler audio...");

    const promises = fillerPhrases.map(async (phrase) => {
      try {
        const resp = await fetch(synthesizeEndpoint, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            text: phrase,
            speaker,
            skip_split: true,
            fast_mode: true,
          }),
        });
        if (resp.ok) {
          const blob = await resp.blob();
          fillerCache.set(phrase, blob);
        }
      } catch {
        // Ignore individual filler failures
      }
    });

    await Promise.allSettled(promises);
    console.log(
      `[VoiceConversation] Fillers cached: ${fillerCache.size}/${fillerPhrases.length}`
    );
  }, [synthesizeEndpoint, speaker, fillerPhrases]);

  const playFiller = useCallback(() => {
    if (fillerPlayedRef.current || playbackAbortRef.current) return;

    const cached = Array.from(fillerCache.entries());
    if (cached.length === 0) return;

    const [phrase, blob] = cached[Math.floor(Math.random() * cached.length)];
    fillerPlayedRef.current = true;
    console.log("[VoiceConversation] Playing filler:", phrase);

    const url = URL.createObjectURL(blob);
    const audio = new Audio(url);
    audio.playbackRate = playbackRate;
    currentAudioRef.current = audio;
    isPlayingRef.current = true;
    setState("speaking");

    audio.onended = () => {
      URL.revokeObjectURL(url);
      currentAudioRef.current = null;
      isPlayingRef.current = false;
    };

    audio.onerror = () => {
      URL.revokeObjectURL(url);
      currentAudioRef.current = null;
      isPlayingRef.current = false;
    };

    audio.play().catch(() => {
      isPlayingRef.current = false;
    });
  }, [playbackRate]);

  // -- TTS: fire a single sentence --

  const fireTTS = useCallback(
    (sentence: string): Promise<Blob | null> => {
      const cleaned = stripMarkdown(sentence).trim();
      console.log("[VoiceConversation] fireTTS:", cleaned.slice(0, 80));
      if (!cleaned || cleaned.length < 5) return Promise.resolve(null);

      return fetch(synthesizeEndpoint, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          text: cleaned,
          speaker,
          audience_mode: audienceMode,
          skip_split: true,
          fast_mode: true,
        }),
      })
        .then((resp) => {
          if (!resp.ok) throw new Error(`TTS ${resp.status}`);
          return resp.blob();
        })
        .catch((err) => {
          console.error("[VoiceConversation] TTS error:", err);
          return null;
        });
    },
    [synthesizeEndpoint, speaker, audienceMode]
  );

  // -- Audio queue player --

  const playNextInQueue = useCallback(async () => {
    if (isPlayingRef.current || playbackAbortRef.current) return;
    if (audioQueueRef.current.length === 0) {
      isPlayingRef.current = false;
      return;
    }

    isPlayingRef.current = true;
    const blobPromise = audioQueueRef.current.shift()!;

    try {
      const blob = await blobPromise;
      if (!blob || playbackAbortRef.current) {
        isPlayingRef.current = false;
        playNextInQueue();
        return;
      }

      const url = URL.createObjectURL(blob);
      const audio = new Audio(url);
      audio.playbackRate = playbackRate;
      currentAudioRef.current = audio;

      audio.onended = () => {
        URL.revokeObjectURL(url);
        currentAudioRef.current = null;
        isPlayingRef.current = false;
        if (!playbackAbortRef.current) {
          playNextInQueue();
        }
      };

      audio.onerror = () => {
        URL.revokeObjectURL(url);
        currentAudioRef.current = null;
        isPlayingRef.current = false;
        if (!playbackAbortRef.current) {
          playNextInQueue();
        }
      };

      setState("speaking");
      await audio.play();
    } catch {
      isPlayingRef.current = false;
      if (!playbackAbortRef.current) {
        playNextInQueue();
      }
    }
  }, [playbackRate]);

  const enqueueTTS = useCallback(
    (sentence: string) => {
      const promise = fireTTS(sentence);
      audioQueueRef.current.push(promise);
      if (!isPlayingRef.current) {
        playNextInQueue();
      }
    },
    [fireTTS, playNextInQueue]
  );

  // -- onTextDelta: called by useChat during SSE stream --

  const onTextDelta = useCallback(
    (delta: string, accumulated: string) => {
      if (!isActiveRef.current) return;

      setAgentText(accumulated);
      sentenceBufferRef.current += delta;

      const { complete, pending } = detectSentenceBoundaries(
        sentenceBufferRef.current
      );

      for (const sentence of complete) {
        if (!firedSentencesRef.current.includes(sentence)) {
          firedSentencesRef.current.push(sentence);
          enqueueTTS(sentence);
        }
      }

      sentenceBufferRef.current = pending;
    },
    [enqueueTTS]
  );

  // -- onStreamComplete: called by useChat when SSE finishes --

  const onStreamComplete = useCallback(
    (_fullText: string) => {
      if (!isActiveRef.current) return;

      const remaining = sentenceBufferRef.current.trim();
      if (remaining && remaining.length >= 10) {
        const MAX_CHUNK = 200;
        if (remaining.length <= MAX_CHUNK) {
          enqueueTTS(remaining);
        } else {
          const chunks = remaining.match(/.{1,200}(?:\s|$)/g) || [remaining];
          for (const chunk of chunks) {
            if (chunk.trim().length >= 10) {
              enqueueTTS(chunk.trim());
            }
          }
        }
      }
      sentenceBufferRef.current = "";
      firedSentencesRef.current = [];

      const checkDone = setInterval(() => {
        if (
          audioQueueRef.current.length === 0 &&
          !isPlayingRef.current &&
          !playbackAbortRef.current &&
          isActiveRef.current
        ) {
          clearInterval(checkDone);
          startListening();
        }
      }, 200);
    },
    [enqueueTTS]
  );

  // -- ASR: transcribe recorded audio --

  const transcribe = useCallback(
    async (webmBlob: Blob) => {
      if (webmBlob.size === 0 || !isActiveRef.current) {
        if (isActiveRef.current) startListening();
        else setState("idle");
        return;
      }

      setState("transcribing");

      try {
        const audioCtx = new AudioContext();
        const arrayBuffer = await webmBlob.arrayBuffer();
        const audioBuffer = await audioCtx.decodeAudioData(arrayBuffer);
        const wavBlob = audioBufferToWav(audioBuffer, ASR_SAMPLE_RATE);
        audioCtx.close();

        const formData = new FormData();
        formData.append("file", wavBlob, "recording.wav");

        const resp = await fetch(transcribeEndpoint, {
          method: "POST",
          body: formData,
        });

        if (!resp.ok) throw new Error(`ASR ${resp.status}`);

        const data = await resp.json();
        const text = data.text?.trim();

        if (!text) {
          if (isActiveRef.current) startListening();
          return;
        }

        setTranscript(text);
        setState("streaming");

        sentenceBufferRef.current = "";
        firedSentencesRef.current = [];
        playbackAbortRef.current = false;
        fillerPlayedRef.current = false;
        setAgentText("");

        playFiller();

        if (sendMessage) {
          await sendMessage(text);
        }
      } catch (err) {
        console.error("[VoiceConversation] ASR error:", err);
        if (isActiveRef.current) startListening();
      }
    },
    [transcribeEndpoint, sendMessage, playFiller]
  );

  // -- Listening: mic + VAD --

  const startListening = useCallback(async () => {
    cleanupMic();

    if (!isActiveRef.current) {
      setState("idle");
      return;
    }

    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      streamRef.current = stream;

      const audioCtx = new AudioContext();
      audioContextRef.current = audioCtx;
      const source = audioCtx.createMediaStreamSource(stream);
      const analyser = audioCtx.createAnalyser();
      analyser.fftSize = 512;
      source.connect(analyser);
      analyserRef.current = analyser;

      const recorder = new MediaRecorder(stream, { mimeType: "audio/webm" });
      mediaRecorderRef.current = recorder;
      audioChunksRef.current = [];

      recorder.ondataavailable = (e) => {
        if (e.data.size > 0) audioChunksRef.current.push(e.data);
      };

      recorder.onstop = () => {
        const blob = new Blob(audioChunksRef.current, { type: "audio/webm" });
        transcribe(blob);
      };

      recorder.start();
      setState("listening");
      speechDetectedRef.current = false;
      silenceStartRef.current = null;

      vadIntervalRef.current = setInterval(() => {
        if (!analyserRef.current) return;

        const level = computeVolumeLevel(analyserRef.current);
        setVolumeLevel(level);

        if (level > speechThreshold) {
          speechDetectedRef.current = true;
          silenceStartRef.current = null;
        } else if (speechDetectedRef.current) {
          if (!silenceStartRef.current) {
            silenceStartRef.current = Date.now();
          } else if (Date.now() - silenceStartRef.current > silenceDurationMs) {
            if (vadIntervalRef.current) {
              clearInterval(vadIntervalRef.current);
              vadIntervalRef.current = null;
            }
            if (recorder.state !== "inactive") {
              recorder.stop();
            }
            streamRef.current?.getTracks().forEach((t) => t.stop());
          }
        }
      }, VAD_POLL_INTERVAL_MS);
    } catch (err) {
      console.error("[VoiceConversation] Microphone error:", err);
      setState("idle");
      isActiveRef.current = false;
    }
  }, [cleanupMic, speechThreshold, silenceDurationMs, transcribe]);

  // -- Public API --

  const start = useCallback(() => {
    isActiveRef.current = true;
    playbackAbortRef.current = false;
    setTranscript("");
    setAgentText("");
    warmupFillers();
    startListening();
  }, [startListening, warmupFillers]);

  const stop = useCallback(() => {
    isActiveRef.current = false;
    cleanupMic();
    stopPlayback();
    setState("idle");
    setTranscript("");
    setAgentText("");
    setVolumeLevel(0);
    sentenceBufferRef.current = "";
    firedSentencesRef.current = [];
  }, [cleanupMic, stopPlayback]);

  const interrupt = useCallback(() => {
    stopPlayback();
    cancelStream?.();
    sentenceBufferRef.current = "";
    firedSentencesRef.current = [];
    playbackAbortRef.current = false;
    startListening();
  }, [stopPlayback, cancelStream, startListening]);

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      isActiveRef.current = false;
      cleanupMic();
      stopPlayback();
    };
  }, [cleanupMic, stopPlayback]);

  return {
    state,
    transcript,
    agentText,
    volumeLevel,
    isActive: state !== "idle",
    start,
    stop,
    interrupt,
    onTextDelta,
    onStreamComplete,
  };
}

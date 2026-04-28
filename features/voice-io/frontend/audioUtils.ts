/**
 * Shared Audio Utilities
 *
 * Zero-dependency audio helpers for voice I/O:
 * - WAV encoding from AudioBuffer
 * - Markdown stripping for TTS input
 * - Sentence boundary detection for streaming TTS
 * - Volume level computation from AnalyserNode
 */

/**
 * Convert an AudioBuffer to a 16kHz mono WAV Blob.
 * Pure JS using DataView -- no dependencies.
 */
export function audioBufferToWav(
  buffer: AudioBuffer,
  targetSampleRate = 16000
): Blob {
  // Get mono channel (average if stereo)
  let samples: Float32Array;
  if (buffer.numberOfChannels === 1) {
    samples = buffer.getChannelData(0);
  } else {
    const left = buffer.getChannelData(0);
    const right = buffer.getChannelData(1);
    samples = new Float32Array(left.length);
    for (let i = 0; i < left.length; i++) {
      samples[i] = (left[i] + right[i]) / 2;
    }
  }

  // Resample if needed
  if (buffer.sampleRate !== targetSampleRate) {
    const ratio = buffer.sampleRate / targetSampleRate;
    const newLength = Math.round(samples.length / ratio);
    const resampled = new Float32Array(newLength);
    for (let i = 0; i < newLength; i++) {
      resampled[i] = samples[Math.round(i * ratio)];
    }
    samples = resampled;
  }

  // Convert float32 [-1,1] to int16
  const int16 = new Int16Array(samples.length);
  for (let i = 0; i < samples.length; i++) {
    const s = Math.max(-1, Math.min(1, samples[i]));
    int16[i] = s < 0 ? s * 0x8000 : s * 0x7fff;
  }

  // Build WAV header + data
  const wavBuffer = new ArrayBuffer(44 + int16.length * 2);
  const view = new DataView(wavBuffer);

  const writeString = (offset: number, str: string) => {
    for (let i = 0; i < str.length; i++)
      view.setUint8(offset + i, str.charCodeAt(i));
  };

  writeString(0, "RIFF");
  view.setUint32(4, 36 + int16.length * 2, true);
  writeString(8, "WAVE");
  writeString(12, "fmt ");
  view.setUint32(16, 16, true); // chunk size
  view.setUint16(20, 1, true); // PCM
  view.setUint16(22, 1, true); // mono
  view.setUint32(24, targetSampleRate, true);
  view.setUint32(28, targetSampleRate * 2, true); // byte rate
  view.setUint16(32, 2, true); // block align
  view.setUint16(34, 16, true); // bits per sample
  writeString(36, "data");
  view.setUint32(40, int16.length * 2, true);

  const output = new Uint8Array(wavBuffer);
  output.set(new Uint8Array(int16.buffer), 44);

  return new Blob([wavBuffer], { type: "audio/wav" });
}

/**
 * Strip markdown formatting for cleaner TTS input.
 */
export function stripMarkdown(text: string): string {
  return text
    .replace(/```[\s\S]*?```/g, "") // code blocks
    .replace(/`([^`]+)`/g, "$1") // inline code
    .replace(/#{1,6}\s+/g, "") // headers
    .replace(/\*\*([^*]+)\*\*/g, "$1") // bold
    .replace(/\*([^*]+)\*/g, "$1") // italic
    .replace(/\[([^\]]+)\]\([^)]+\)/g, "$1") // links
    .replace(/^[-*+]\s+/gm, "") // bullets
    .replace(/^\d+\.\s+/gm, "") // numbered lists
    .replace(/^>\s+/gm, "") // blockquotes
    .replace(/\|[^\n]+\|/g, "") // tables
    .replace(/---+/g, "") // horizontal rules
    .replace(/\n{3,}/g, "\n\n") // collapse newlines
    .trim();
}

/**
 * Detect sentence boundaries in streaming text.
 *
 * Returns an object with:
 * - `complete`: Array of complete sentences detected so far
 * - `pending`: The remaining text that hasn't ended with a sentence terminator
 */
export function detectSentenceBoundaries(text: string): {
  complete: string[];
  pending: string;
} {
  const complete: string[] = [];

  // Split on sentence-ending punctuation OR newlines (markdown list items, paragraphs).
  const splitPattern =
    /(?:(?<!\b(?:Mr|Mrs|Ms|Dr|Prof|Sr|Jr|Inc|Ltd|Corp|U\.S|etc|vs|e\.g|i\.e))(?<!\d)[.!?]+(?:\s+|$)|\n(?:\s*[-*]\s|\s*\d+\.\s|\s*\n))/g;

  let lastIndex = 0;
  let match: RegExpExecArray | null;

  while ((match = splitPattern.exec(text)) !== null) {
    const sentenceEnd = match.index + match[0].length;
    const sentence = text.slice(lastIndex, sentenceEnd).trim();
    if (sentence.length >= 10) {
      complete.push(sentence);
    }
    lastIndex = sentenceEnd;
  }

  const pending = text.slice(lastIndex).trim();

  return { complete, pending };
}

/**
 * Compute RMS volume level from AnalyserNode frequency data.
 * Returns a value between 0 and 255.
 */
export function computeVolumeLevel(analyser: AnalyserNode): number {
  const data = new Uint8Array(analyser.frequencyBinCount);
  analyser.getByteFrequencyData(data);
  let sum = 0;
  for (let i = 0; i < data.length; i++) {
    sum += data[i] * data[i];
  }
  return Math.sqrt(sum / data.length);
}

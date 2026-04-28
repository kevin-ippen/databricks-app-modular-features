"""
TTS (Text-to-Speech) Router

Provides a FastAPI router for synthesizing speech from text via a configurable
model serving endpoint. Includes sentence splitting, concurrent synthesis,
WAV chunk concatenation with crossfade, and speech normalization.

Usage:
    from features.voice_io.backend.tts import create_tts_router

    router = create_tts_router(
        token_provider=my_get_token,
        host_provider=my_get_host,
        endpoint_name="my-tts-endpoint",
    )
    app.include_router(router)
"""

import asyncio
import base64
import io
import logging
import re
import struct
import array
import time
from typing import Callable, List, Optional

import httpx
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response
from pydantic import BaseModel

logger = logging.getLogger(__name__)


# =============================================================================
# Request model
# =============================================================================

class SynthesizeRequest(BaseModel):
    """Request for text-to-speech synthesis."""
    text: str
    speaker: str = "Ryan"
    language: str = "English"
    audience_mode: str = "exec"  # exec | business | technical
    verbosity: int = 1  # 0..3
    skip_split: bool = False  # Voice mode: skip sentence splitting for pre-split input
    fast_mode: bool = False  # Voice mode: skip normalization for pre-processed text


# =============================================================================
# Internal helpers
# =============================================================================

def _split_sentences(text: str) -> List[str]:
    """Split text into sentence-level chunks for natural TTS prosody."""
    raw = re.split(r"(?<=[.!?])\s+", text.strip())
    sentences = []
    for s in raw:
        s = s.strip()
        if not s:
            continue
        if sentences and len(s) < 20:
            sentences[-1] = sentences[-1] + " " + s
        else:
            sentences.append(s)
    return sentences if sentences else [text.strip()]


def _extract_audio_b64(result: dict | list) -> str:
    """Extract base64 audio from TTS endpoint response."""
    if isinstance(result, dict):
        predictions = result.get("predictions", [])
        if predictions:
            if isinstance(predictions[0], dict):
                return predictions[0].get("audio_b64", "") or predictions[0].get(
                    "audio", ""
                )
            elif isinstance(predictions[0], str):
                return predictions[0]
        return result.get("audio_b64", "") or result.get("audio", "")
    elif isinstance(result, list) and len(result) > 0:
        if isinstance(result[0], dict):
            return result[0].get("audio_b64", "") or result[0].get("audio", "")
        elif isinstance(result[0], str):
            return result[0]
    return ""


def _concat_wav_chunks(
    chunks: List[bytes], silence_ms: int = 60, fade_ms: int = 15
) -> bytes:
    """
    Concatenate WAV chunks with crossfade and silence padding.

    - fade_ms: fade-out/fade-in at chunk boundaries to eliminate clicks
    - silence_ms: silence gap between sentences for natural pacing
    """
    if len(chunks) == 1:
        return chunks[0]

    # Parse first chunk to get WAV params
    first = chunks[0]
    sample_rate = struct.unpack_from("<I", first, 24)[0]
    num_channels = struct.unpack_from("<H", first, 22)[0]
    bits_per_sample = struct.unpack_from("<H", first, 34)[0]
    bytes_per_sample = bits_per_sample // 8

    logger.info(
        f"[WAV_CONCAT] sr={sample_rate}, ch={num_channels}, bps={bits_per_sample}"
    )

    silence_samples = int(sample_rate * silence_ms / 1000) * num_channels
    silence_bytes = b"\x00" * (silence_samples * bytes_per_sample)

    fade_samples = int(sample_rate * fade_ms / 1000)

    def _apply_fade(
        pcm: bytes, fade_in: bool = False, fade_out: bool = False
    ) -> bytes:
        if not fade_in and not fade_out:
            return pcm
        if bits_per_sample != 16:
            return pcm

        samples = array.array("h")
        samples.frombytes(pcm)
        n = len(samples)

        if fade_in and n > fade_samples:
            for i in range(fade_samples):
                samples[i] = int(samples[i] * (i / fade_samples))
        if fade_out and n > fade_samples:
            for i in range(fade_samples):
                idx = n - 1 - i
                samples[idx] = int(samples[idx] * (i / fade_samples))

        return samples.tobytes()

    pcm_parts = []
    for i, wav_bytes in enumerate(chunks):
        if len(wav_bytes) <= 44:
            continue
        pcm = wav_bytes[44:]
        pcm = _apply_fade(
            pcm, fade_in=(i > 0), fade_out=(i < len(chunks) - 1)
        )
        pcm_parts.append(pcm)
        if i < len(chunks) - 1:
            pcm_parts.append(silence_bytes)

    all_pcm = b"".join(pcm_parts)
    data_size = len(all_pcm)

    header = io.BytesIO()
    header.write(b"RIFF")
    header.write(struct.pack("<I", 36 + data_size))
    header.write(b"WAVE")
    header.write(b"fmt ")
    header.write(struct.pack("<I", 16))
    header.write(struct.pack("<H", 1))  # PCM
    header.write(struct.pack("<H", num_channels))
    header.write(struct.pack("<I", sample_rate))
    byte_rate = sample_rate * num_channels * bytes_per_sample
    header.write(struct.pack("<I", byte_rate))
    block_align = num_channels * bytes_per_sample
    header.write(struct.pack("<H", block_align))
    header.write(struct.pack("<H", bits_per_sample))
    header.write(b"data")
    header.write(struct.pack("<I", data_size))

    duration_sec = data_size / byte_rate if byte_rate else 0
    logger.info(
        f"[WAV_CONCAT] Output: {data_size} bytes, {duration_sec:.1f}s, {len(chunks)} chunks"
    )

    return header.getvalue() + all_pcm


# =============================================================================
# Router factory
# =============================================================================

def create_tts_router(
    token_provider: Callable[[Request], str],
    host_provider: Callable[[], str],
    endpoint_name: str,
    prefix: str = "/voice",
    tags: Optional[list] = None,
    timeout: float = 120.0,
) -> APIRouter:
    """
    Create a FastAPI router with a TTS synthesis endpoint.

    Args:
        token_provider: Function that extracts auth token from request.
        host_provider: Function that returns the Databricks workspace host URL.
        endpoint_name: Name of the serving endpoint for TTS.
        prefix: URL prefix for the router. Default: "/voice"
        tags: OpenAPI tags. Default: ["voice"]
        timeout: HTTP timeout for TTS requests in seconds. Default: 120.
    """
    router = APIRouter(prefix=prefix, tags=tags or ["voice"])

    @router.post("/synthesize")
    async def synthesize_speech(
        request: Request,
        body: SynthesizeRequest,
    ):
        """
        Convert text to speech using the configured TTS serving endpoint.

        Normalizes text, splits into sentences for natural prosody,
        generates audio per sentence concurrently, and concatenates WAV chunks.
        """
        token = token_provider(request)
        host = host_provider()

        try:
            t_start = time.monotonic()

            if body.fast_mode:
                spoken_text = body.text.strip()
                logger.info(
                    f"[SYNTHESIZE] fast_mode: {len(spoken_text)} chars (skipped normalization)"
                )
            else:
                # Import speech normalizer (optional dependency)
                try:
                    from .speech_normalizer import normalize_for_speech

                    spoken_text = normalize_for_speech(
                        text=body.text,
                        audience_mode=body.audience_mode,
                        verbosity=body.verbosity,
                        max_chars=1200,
                    )
                except ImportError:
                    spoken_text = body.text.strip()

                logger.info(
                    f"[SYNTHESIZE] Normalized {len(body.text)} -> {len(spoken_text)} chars "
                    f"(mode={body.audience_mode})"
                )

            if body.skip_split:
                sentences = [spoken_text]
            else:
                sentences = _split_sentences(spoken_text)
            logger.info(
                f"[SYNTHESIZE] Split into {len(sentences)} chunks "
                f"(skip_split={body.skip_split}): {[len(s) for s in sentences]}"
            )

            endpoint_url = (
                f"{host}/serving-endpoints/{endpoint_name}/invocations"
            )
            headers = {
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            }

            async def _tts_one(
                client: httpx.AsyncClient, idx: int, text_chunk: str
            ) -> bytes:
                t0 = time.monotonic()
                resp = await client.post(
                    endpoint_url,
                    headers=headers,
                    json={
                        "dataframe_records": [
                            {
                                "text": text_chunk,
                                "language": body.language,
                            }
                        ],
                    },
                )
                resp.raise_for_status()
                result = resp.json()
                audio_b64 = _extract_audio_b64(result)
                if not audio_b64:
                    logger.warning(
                        f"[SYNTHESIZE] Chunk {idx} empty audio: {text_chunk[:60]}..."
                    )
                    return b""
                wav = base64.b64decode(audio_b64)
                elapsed = time.monotonic() - t0
                logger.info(
                    f"[SYNTHESIZE] Chunk {idx}: {len(text_chunk)} chars -> "
                    f"{len(wav)} bytes in {elapsed:.1f}s"
                )
                return wav

            t_infer = time.monotonic()
            async with httpx.AsyncClient(timeout=timeout) as client:
                tasks = [
                    _tts_one(client, i, s) for i, s in enumerate(sentences)
                ]
                wav_chunks = await asyncio.gather(*tasks, return_exceptions=True)
            t_infer_done = time.monotonic()

            valid_chunks = []
            for i, chunk in enumerate(wav_chunks):
                if isinstance(chunk, Exception):
                    logger.warning(f"[SYNTHESIZE] Chunk {i} failed: {chunk}")
                elif chunk and len(chunk) > 44:
                    valid_chunks.append(chunk)

            if not valid_chunks:
                raise HTTPException(
                    status_code=502,
                    detail="TTS endpoint returned no audio for any chunk",
                )

            audio_bytes = _concat_wav_chunks(valid_chunks)
            t_total = time.monotonic() - t_start
            logger.info(
                f"[SYNTHESIZE] Done: {len(audio_bytes)} bytes, "
                f"{len(valid_chunks)}/{len(sentences)} chunks, "
                f"infer={t_infer_done - t_infer:.1f}s, total={t_total:.1f}s"
            )

            return Response(
                content=audio_bytes,
                media_type="audio/wav",
                headers={
                    "Content-Disposition": "inline; filename=speech.wav"
                },
            )

        except httpx.HTTPStatusError as e:
            logger.error(
                f"[SYNTHESIZE] TTS endpoint error: {e.response.status_code} {e.response.text}"
            )
            raise HTTPException(
                status_code=502,
                detail=f"TTS service error: {e.response.status_code}",
            )
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"[SYNTHESIZE] Error: {e}", exc_info=True)
            raise HTTPException(status_code=500, detail=str(e))

    return router

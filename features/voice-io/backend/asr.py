"""
ASR (Automatic Speech Recognition) Router

Provides a FastAPI router for transcribing audio files via a configurable
model serving endpoint. Accepts audio uploads (webm, wav, mp3) and returns
transcribed text.

Usage:
    from features.voice_io.backend.asr import create_asr_router

    router = create_asr_router(
        token_provider=my_get_token,
        host_provider=my_get_host,
        endpoint_name="my-asr-endpoint",
    )
    app.include_router(router)
"""

import base64
import logging
from typing import Callable, Optional

import httpx
from fastapi import APIRouter, HTTPException, Request, UploadFile, File
from pydantic import BaseModel

logger = logging.getLogger(__name__)


class TranscriptionResponse(BaseModel):
    """Response from speech-to-text transcription."""
    text: str


def create_asr_router(
    token_provider: Callable[[Request], str],
    host_provider: Callable[[], str],
    endpoint_name: str,
    prefix: str = "/voice",
    tags: Optional[list] = None,
    timeout: float = 180.0,
) -> APIRouter:
    """
    Create a FastAPI router with an ASR transcription endpoint.

    Args:
        token_provider: Function that extracts auth token from request.
            Signature: (request: Request) -> str
        host_provider: Function that returns the Databricks workspace host URL.
            Signature: () -> str
        endpoint_name: Name of the serving endpoint for ASR.
        prefix: URL prefix for the router. Default: "/voice"
        tags: OpenAPI tags. Default: ["voice"]
        timeout: HTTP timeout for ASR requests in seconds. Default: 180.
    """
    router = APIRouter(prefix=prefix, tags=tags or ["voice"])

    @router.post("/transcribe", response_model=TranscriptionResponse)
    async def transcribe_audio(
        request: Request,
        file: UploadFile = File(...),
    ):
        """
        Transcribe audio to text using the configured ASR serving endpoint.

        Accepts audio file upload (webm, wav, mp3, etc.) and returns transcribed text.
        """
        token = token_provider(request)
        host = host_provider()

        try:
            audio_bytes = await file.read()
            audio_b64 = base64.b64encode(audio_bytes).decode("utf-8")

            endpoint_url = f"{host}/serving-endpoints/{endpoint_name}/invocations"

            async with httpx.AsyncClient(timeout=timeout) as client:
                resp = await client.post(
                    endpoint_url,
                    headers={
                        "Authorization": f"Bearer {token}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "dataframe_records": [
                            {"audio_b64": audio_b64, "language": "English"}
                        ],
                    },
                )
                resp.raise_for_status()
                result = resp.json()

            # Extract transcription from response
            text = ""
            if isinstance(result, dict):
                text = (
                    result.get("predictions", [{}])[0].get("text", "")
                    if result.get("predictions")
                    else result.get("text", "")
                )
            elif isinstance(result, list) and len(result) > 0:
                text = (
                    result[0].get("text", "")
                    if isinstance(result[0], dict)
                    else str(result[0])
                )

            logger.info(f"[TRANSCRIBE] Got {len(text)} chars from ASR endpoint")
            return TranscriptionResponse(text=text)

        except httpx.HTTPStatusError as e:
            logger.error(
                f"[TRANSCRIBE] ASR endpoint error: {e.response.status_code} {e.response.text}"
            )
            raise HTTPException(
                status_code=502,
                detail=f"ASR service error: {e.response.status_code}",
            )
        except Exception as e:
            logger.error(f"[TRANSCRIBE] Error: {e}", exc_info=True)
            raise HTTPException(status_code=500, detail=str(e))

    return router

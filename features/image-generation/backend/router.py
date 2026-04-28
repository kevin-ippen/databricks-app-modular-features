"""FastAPI routes for image generation and vision analysis."""

import logging
from typing import Optional
from fastapi import APIRouter, HTTPException, Request, UploadFile, File, Form
from fastapi.responses import Response
from pydantic import BaseModel
import base64

from .client import ImageClient, ImageResult

logger = logging.getLogger(__name__)


class GenerateRequest(BaseModel):
    prompt: str
    input_images: Optional[list[str]] = None  # base64 data URIs or URLs
    model: Optional[str] = None


class AnalyzeRequest(BaseModel):
    images: list[str]  # base64 data URIs or URLs
    prompt: str = "Describe this image in detail."
    model: Optional[str] = None


class ImageResponse(BaseModel):
    image_base64: Optional[str] = None
    image_url: Optional[str] = None
    text: Optional[str] = None
    model: str = ""


def create_image_router(
    token_provider: callable = None,
    host_provider: callable = None,
    default_generation_model: str = "databricks-gpt-5-2",
    default_vision_model: str = "databricks-gpt-5-2",
) -> APIRouter:
    """Create a FastAPI router for image generation and vision.

    Args:
        token_provider: Callable returning auth token. Default: reads DATABRICKS_TOKEN env.
        host_provider: Callable returning workspace host. Default: reads DATABRICKS_HOST env.
        default_generation_model: Default model for image generation.
        default_vision_model: Default model for vision analysis.
    """
    router = APIRouter(tags=["images"])

    def _get_client(request: Request, model: str) -> ImageClient:
        import os
        host = host_provider() if host_provider else os.environ.get("DATABRICKS_HOST", "")
        token_fn = token_provider or (lambda: request.headers.get("x-forwarded-access-token") or os.environ.get("DATABRICKS_TOKEN", ""))
        return ImageClient(host=host, token_provider=token_fn, model=model)

    @router.post("/generate", response_model=ImageResponse)
    async def generate_image(body: GenerateRequest, request: Request):
        """Generate an image from a text prompt, optionally with input images."""
        try:
            client = _get_client(request, body.model or default_generation_model)
            result = await client.agenerate(
                prompt=body.prompt,
                input_images=body.input_images,
                model=body.model,
            )
            return ImageResponse(
                image_base64=result.image_base64,
                image_url=result.image_url,
                text=result.text,
                model=result.model,
            )
        except Exception as e:
            logger.error(f"Image generation failed: {e}")
            raise HTTPException(status_code=500, detail=str(e))

    @router.post("/analyze", response_model=ImageResponse)
    async def analyze_image(body: AnalyzeRequest, request: Request):
        """Analyze images using a vision-capable model."""
        try:
            client = _get_client(request, body.model or default_vision_model)
            result = await client.aanalyze(
                images=body.images,
                prompt=body.prompt,
                model=body.model,
            )
            return ImageResponse(text=result.text, model=result.model)
        except Exception as e:
            logger.error(f"Image analysis failed: {e}")
            raise HTTPException(status_code=500, detail=str(e))

    @router.post("/analyze-upload", response_model=ImageResponse)
    async def analyze_uploaded_image(
        request: Request,
        file: UploadFile = File(...),
        prompt: str = Form("Describe this image in detail."),
        model: Optional[str] = Form(None),
    ):
        """Upload an image file and analyze it."""
        try:
            contents = await file.read()
            mime = file.content_type or "image/png"
            data_uri = ImageClient.encode_bytes(contents, mime)

            client = _get_client(request, model or default_vision_model)
            result = await client.aanalyze(
                images=[data_uri],
                prompt=prompt,
                model=model,
            )
            return ImageResponse(text=result.text, model=result.model)
        except Exception as e:
            logger.error(f"Image upload analysis failed: {e}")
            raise HTTPException(status_code=500, detail=str(e))

    return router

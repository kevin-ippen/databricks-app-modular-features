"""Image generation and vision analysis via Databricks FMAPI Responses API."""

import base64, logging, os
from dataclasses import dataclass, field
from typing import Optional
from pathlib import Path

logger = logging.getLogger(__name__)

@dataclass
class ImageResult:
    """Result from an image generation or vision request."""
    image_base64: Optional[str] = None  # base64-encoded image data
    image_url: Optional[str] = None     # URL if returned by model
    text: Optional[str] = None          # text response (vision analysis or caption)
    model: str = ""
    usage: dict = field(default_factory=dict)

    def save(self, path: str) -> str:
        """Save image to file. Returns the path."""
        if self.image_base64:
            data = self.image_base64
            if "," in data:
                data = data.split(",", 1)[1]
            Path(path).write_bytes(base64.b64decode(data))
            return path
        raise ValueError("No image data to save")


class ImageClient:
    """FMAPI client for image generation and vision analysis.

    Uses the OpenAI-compatible Responses API with image_generation tool.
    Works with any OpenAI model served via Databricks FMAPI (e.g., databricks-gpt-5-2).
    """

    def __init__(
        self,
        host: Optional[str] = None,
        token_provider: Optional[callable] = None,
        model: str = "databricks-gpt-5-2",
    ):
        self.host = (host or os.environ.get("DATABRICKS_HOST", "")).rstrip("/")
        self._token_provider = token_provider or (lambda: os.environ.get("DATABRICKS_TOKEN", ""))
        self.model = model

    def _get_client(self):
        """Lazy OpenAI client creation."""
        from openai import OpenAI
        return OpenAI(
            base_url=f"{self.host}/serving-endpoints",
            api_key=self._token_provider(),
        )

    async def _get_async_client(self):
        """Lazy async OpenAI client creation."""
        from openai import AsyncOpenAI
        return AsyncOpenAI(
            base_url=f"{self.host}/serving-endpoints",
            api_key=self._token_provider(),
        )

    @staticmethod
    def encode_image(path: str) -> str:
        """Encode a local image file as a base64 data URI."""
        import mimetypes
        mime = mimetypes.guess_type(path)[0] or "image/png"
        with open(path, "rb") as f:
            b64 = base64.b64encode(f.read()).decode("utf-8")
        return f"data:{mime};base64,{b64}"

    @staticmethod
    def encode_bytes(data: bytes, mime: str = "image/png") -> str:
        """Encode raw bytes as a base64 data URI."""
        b64 = base64.b64encode(data).decode("utf-8")
        return f"data:{mime};base64,{b64}"

    def generate(
        self,
        prompt: str,
        input_images: list[str] | None = None,
        model: str | None = None,
    ) -> ImageResult:
        """Generate an image from text (and optionally input images).

        Args:
            prompt: Text description of the image to generate.
            input_images: Optional list of image URLs or base64 data URIs for
                         image-to-image generation (style transfer, editing, etc.).
            model: Override the default model.

        Returns:
            ImageResult with generated image data.
        """
        client = self._get_client()

        content = [{"type": "input_text", "text": prompt}]
        if input_images:
            for img in input_images:
                content.append({"type": "input_image", "image_url": img})

        resp = client.responses.create(
            model=model or self.model,
            input=[{"role": "user", "content": content}],
            tools=[{"type": "image_generation"}],
            tool_choice="auto",
        )

        return self._parse_response(resp)

    async def agenerate(
        self,
        prompt: str,
        input_images: list[str] | None = None,
        model: str | None = None,
    ) -> ImageResult:
        """Async version of generate()."""
        client = await self._get_async_client()

        content = [{"type": "input_text", "text": prompt}]
        if input_images:
            for img in input_images:
                content.append({"type": "input_image", "image_url": img})

        resp = await client.responses.create(
            model=model or self.model,
            input=[{"role": "user", "content": content}],
            tools=[{"type": "image_generation"}],
            tool_choice="auto",
        )

        return self._parse_response(resp)

    def analyze(
        self,
        images: list[str],
        prompt: str = "Describe this image in detail.",
        model: str | None = None,
    ) -> ImageResult:
        """Analyze images using a vision-capable model.

        Args:
            images: List of image URLs or base64 data URIs.
            prompt: Analysis instruction.
            model: Override model (use a vision-capable model).

        Returns:
            ImageResult with text analysis.
        """
        # Vision uses the chat completions API, not responses API
        from openai import OpenAI
        client = OpenAI(
            base_url=f"{self.host}/serving-endpoints",
            api_key=self._token_provider(),
        )

        content = [{"type": "text", "text": prompt}]
        for img in images:
            content.append({
                "type": "image_url",
                "image_url": {"url": img},
            })

        resp = client.chat.completions.create(
            model=model or self.model,
            messages=[{"role": "user", "content": content}],
            max_tokens=1024,
        )

        return ImageResult(
            text=resp.choices[0].message.content,
            model=resp.model,
            usage={"prompt_tokens": resp.usage.prompt_tokens, "completion_tokens": resp.usage.completion_tokens} if resp.usage else {},
        )

    async def aanalyze(
        self,
        images: list[str],
        prompt: str = "Describe this image in detail.",
        model: str | None = None,
    ) -> ImageResult:
        """Async version of analyze()."""
        from openai import AsyncOpenAI
        client = AsyncOpenAI(
            base_url=f"{self.host}/serving-endpoints",
            api_key=self._token_provider(),
        )

        content = [{"type": "text", "text": prompt}]
        for img in images:
            content.append({
                "type": "image_url",
                "image_url": {"url": img},
            })

        resp = await client.chat.completions.create(
            model=model or self.model,
            messages=[{"role": "user", "content": content}],
            max_tokens=1024,
        )

        return ImageResult(
            text=resp.choices[0].message.content,
            model=resp.model,
            usage={"prompt_tokens": resp.usage.prompt_tokens, "completion_tokens": resp.usage.completion_tokens} if resp.usage else {},
        )

    def _parse_response(self, resp) -> ImageResult:
        """Extract image data from a Responses API response."""
        result = ImageResult(model=getattr(resp, "model", self.model))

        for item in getattr(resp, "output", []):
            # Check for image content blocks
            for block in getattr(item, "content", []):
                block_type = getattr(block, "type", "")
                if block_type in ("output_image", "image"):
                    b64 = getattr(block, "image_data_base64", None)
                    url = getattr(block, "url", None)
                    if b64:
                        result.image_base64 = b64
                    if url:
                        result.image_url = url
                elif block_type in ("output_text", "text"):
                    result.text = getattr(block, "text", "")

            # Some models return image_generation_call results
            if getattr(item, "type", "") == "image_generation_call":
                result.image_base64 = getattr(item, "result", None)

        # Extract usage if available
        if hasattr(resp, "usage"):
            u = resp.usage
            result.usage = {
                "input_tokens": getattr(u, "input_tokens", 0),
                "output_tokens": getattr(u, "output_tokens", 0),
            }

        return result

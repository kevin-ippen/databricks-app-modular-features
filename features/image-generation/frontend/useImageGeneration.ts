/**
 * React hook for image generation and vision analysis via FMAPI.
 */
import { useState, useCallback } from "react";

interface ImageGenerationConfig {
  generateEndpoint: string;   // e.g., "/api/images/generate"
  analyzeEndpoint: string;    // e.g., "/api/images/analyze"
}

interface GenerateOptions {
  prompt: string;
  inputImages?: string[];     // base64 data URIs or URLs
  model?: string;
}

interface AnalyzeOptions {
  images: string[];           // base64 data URIs or URLs
  prompt?: string;
  model?: string;
}

interface ImageResult {
  imageBase64: string | null;
  imageUrl: string | null;
  text: string | null;
  model: string;
}

export function useImageGeneration(config: ImageGenerationConfig) {
  const [isGenerating, setIsGenerating] = useState(false);
  const [isAnalyzing, setIsAnalyzing] = useState(false);
  const [result, setResult] = useState<ImageResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  const generate = useCallback(async (options: GenerateOptions): Promise<ImageResult | null> => {
    setIsGenerating(true);
    setError(null);
    try {
      const resp = await fetch(config.generateEndpoint, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          prompt: options.prompt,
          input_images: options.inputImages,
          model: options.model,
        }),
      });
      if (!resp.ok) {
        const err = await resp.text();
        throw new Error(err || `HTTP ${resp.status}`);
      }
      const data = await resp.json();
      const imgResult: ImageResult = {
        imageBase64: data.image_base64,
        imageUrl: data.image_url,
        text: data.text,
        model: data.model,
      };
      setResult(imgResult);
      return imgResult;
    } catch (e: any) {
      setError(e.message);
      return null;
    } finally {
      setIsGenerating(false);
    }
  }, [config.generateEndpoint]);

  const analyze = useCallback(async (options: AnalyzeOptions): Promise<ImageResult | null> => {
    setIsAnalyzing(true);
    setError(null);
    try {
      const resp = await fetch(config.analyzeEndpoint, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          images: options.images,
          prompt: options.prompt || "Describe this image in detail.",
          model: options.model,
        }),
      });
      if (!resp.ok) {
        const err = await resp.text();
        throw new Error(err || `HTTP ${resp.status}`);
      }
      const data = await resp.json();
      const imgResult: ImageResult = {
        imageBase64: null,
        imageUrl: null,
        text: data.text,
        model: data.model,
      };
      setResult(imgResult);
      return imgResult;
    } catch (e: any) {
      setError(e.message);
      return null;
    } finally {
      setIsAnalyzing(false);
    }
  }, [config.analyzeEndpoint]);

  /** Convert a File object to a base64 data URI. */
  const fileToDataUri = useCallback(async (file: File): Promise<string> => {
    return new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = () => resolve(reader.result as string);
      reader.onerror = reject;
      reader.readAsDataURL(file);
    });
  }, []);

  return {
    generate,
    analyze,
    fileToDataUri,
    result,
    isGenerating,
    isAnalyzing,
    error,
    clearError: () => setError(null),
    clearResult: () => setResult(null),
  };
}

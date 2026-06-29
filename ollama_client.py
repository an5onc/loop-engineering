"""Thin client over the Ollama HTTP API (no external AI frameworks)."""

import json
import socket
import time
import urllib.error
import urllib.request
from dataclasses import dataclass

import config


class OllamaError(RuntimeError):
    """Raised when the Ollama API call fails."""


@dataclass
class GenResult:
    """One generation result plus the metrics Ollama reports."""

    text: str
    latency_s: float                 # client-measured wall time
    prompt_tokens: int = 0           # prompt_eval_count
    output_tokens: int = 0           # eval_count
    eval_duration_s: float = 0.0     # eval_duration (ns -> s)
    total_duration_s: float = 0.0    # total_duration (ns -> s)

    @property
    def tokens_per_sec(self) -> float:
        if self.eval_duration_s > 0 and self.output_tokens:
            return self.output_tokens / self.eval_duration_s
        return 0.0


class OllamaTimeout(OllamaError):
    """Raised when a generate() call exceeds its wall-clock timeout."""


def generate(model: str, prompt: str, system: str = "", temperature=None,
             timeout=None) -> GenResult:
    """Call POST /api/generate (stream=False) and return text + metrics."""
    if temperature is None:
        temperature = config.TEMPERATURE
    if timeout is None:
        timeout = config.REQUEST_TIMEOUT
    url = f"{config.OLLAMA_HOST}/api/generate"
    payload = {
        "model": model,
        "prompt": prompt,
        "system": system,
        "stream": False,
        "options": {"temperature": temperature},
    }
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url, data=data, headers={"Content-Type": "application/json"}, method="POST"
    )

    start = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = json.loads(resp.read().decode("utf-8"))
    except socket.timeout as exc:
        raise OllamaTimeout(
            f"Ollama call timed out after {timeout}s (model={model})."
        ) from exc
    except urllib.error.URLError as exc:
        if isinstance(getattr(exc, "reason", None), socket.timeout):
            raise OllamaTimeout(
                f"Ollama call timed out after {timeout}s (model={model})."
            ) from exc
        raise OllamaError(
            f"Could not reach Ollama at {config.OLLAMA_HOST}. "
            f"Is `ollama serve` running? Original error: {exc}"
        ) from exc
    except json.JSONDecodeError as exc:
        raise OllamaError(f"Invalid JSON from Ollama: {exc}") from exc
    latency = time.perf_counter() - start

    if "error" in body:
        raise OllamaError(f"Ollama returned an error: {body['error']}")

    return GenResult(
        text=body.get("response", "").strip(),
        latency_s=latency,
        prompt_tokens=int(body.get("prompt_eval_count", 0) or 0),
        output_tokens=int(body.get("eval_count", 0) or 0),
        eval_duration_s=float(body.get("eval_duration", 0) or 0) / 1e9,
        total_duration_s=float(body.get("total_duration", 0) or 0) / 1e9,
    )


def is_alive() -> bool:
    """Return True if the Ollama server responds on /api/tags."""
    url = f"{config.OLLAMA_HOST}/api/tags"
    try:
        with urllib.request.urlopen(url, timeout=5) as resp:
            return resp.status == 200
    except (urllib.error.URLError, OSError):
        return False

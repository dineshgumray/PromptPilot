import json
from urllib import error, parse, request


class LLMClientError(RuntimeError):
    pass


def extract_openai_text(payload):
    text_chunks = []
    output_text = payload.get("output_text")
    if isinstance(output_text, str) and output_text.strip():
        text_chunks.append(output_text.strip())

    for output_item in payload.get("output") or []:
        if output_item.get("type") != "message":
            continue
        for content_item in output_item.get("content", []):
            if content_item.get("type") in {"output_text", "text"} and content_item.get("text"):
                text_chunks.append(content_item["text"].strip())

    if not text_chunks:
        for choice in payload.get("choices") or []:
            text = choice.get("text")
            if text:
                text_chunks.append(text.strip())
                continue

            message = choice.get("message") or {}
            content = message.get("content")
            if isinstance(content, str) and content.strip():
                text_chunks.append(content.strip())
                continue

            for part in content or []:
                if isinstance(part, dict) and part.get("text"):
                    text_chunks.append(part["text"].strip())

    return "\n".join(chunk for chunk in text_chunks if chunk).strip()


def extract_gemini_text(payload):
    text_chunks = []
    for candidate in payload.get("candidates", []):
        content = candidate.get("content", {})
        for part in content.get("parts", []):
            if part.get("text"):
                text_chunks.append(part["text"].strip())

    return "\n".join(chunk for chunk in text_chunks if chunk).strip()


def extract_anthropic_text(payload):
    text_chunks = []
    for content_item in payload.get("content", []):
        if content_item.get("type") == "text" and content_item.get("text"):
            text_chunks.append(content_item["text"].strip())

    return "\n".join(chunk for chunk in text_chunks if chunk).strip()


class BaseHTTPClient:
    DEFAULT_USER_AGENT = "PromptPilot/1.0"

    def __init__(self, timeout=120):
        self.timeout = timeout

    def post_json(self, url, payload, headers, provider_name):
        request_headers = dict(headers)
        request_headers.setdefault("Accept", "application/json")
        request_headers.setdefault("User-Agent", self.DEFAULT_USER_AGENT)
        req = request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers=request_headers,
            method="POST",
        )

        try:
            with request.urlopen(req, timeout=self.timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except error.HTTPError as exc:
            message = exc.read().decode("utf-8", errors="ignore") or exc.reason
            raise LLMClientError(f"{provider_name} rejected the request ({exc.code}): {message}") from exc
        except error.URLError as exc:
            raise LLMClientError(
                f"Could not reach {provider_name}. Check the configured base URL and network access."
            ) from exc


class ResponsesAPIClient(BaseHTTPClient):
    def __init__(self, api_key, base_url, default_model, api_key_name, provider_name, timeout=120):
        super().__init__(timeout=timeout)
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.default_model = default_model
        self.api_key_name = api_key_name
        self.provider_name = provider_name

    def generate(self, prompt, model=None):
        if not self.api_key:
            raise LLMClientError(
                f"Missing {self.api_key_name}. Set it to enable {self.provider_name} generation."
            )

        payload = self.post_json(
            f"{self.base_url}/responses",
            {
                "model": model or self.default_model,
                "input": prompt,
            },
            {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}",
            },
            self.provider_name,
        )
        generated_text = extract_openai_text(payload)
        if not generated_text:
            raise LLMClientError(f"{self.provider_name} returned an empty response payload.")
        return generated_text


class OllamaClient(BaseHTTPClient):
    def __init__(self, base_url, default_model, timeout=120):
        super().__init__(timeout=timeout)
        self.base_url = base_url.rstrip("/")
        self.default_model = default_model

    def generate(self, prompt, model=None):
        payload = self.post_json(
            f"{self.base_url}/api/generate",
            {
                "model": model or self.default_model,
                "prompt": prompt,
                "stream": False,
            },
            {"Content-Type": "application/json"},
            "Ollama",
        )
        generated_text = payload.get("response", "").strip()
        if not generated_text:
            raise LLMClientError("Ollama returned an empty response.")
        return generated_text


class OpenAIClient(ResponsesAPIClient):
    def __init__(self, api_key, base_url, default_model, timeout=120):
        super().__init__(
            api_key=api_key,
            base_url=base_url,
            default_model=default_model,
            api_key_name="OPENAI_API_KEY",
            provider_name="OpenAI",
            timeout=timeout,
        )


class GroqClient(ResponsesAPIClient):
    def __init__(self, api_key, base_url, default_model, timeout=120):
        super().__init__(
            api_key=api_key,
            base_url=base_url,
            default_model=default_model,
            api_key_name="GROQ_API_KEY",
            provider_name="Groq",
            timeout=timeout,
        )


class GeminiClient(BaseHTTPClient):
    def __init__(self, api_key, base_url, default_model, timeout=120):
        super().__init__(timeout=timeout)
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.default_model = default_model

    def generate(self, prompt, model=None):
        if not self.api_key:
            raise LLMClientError("Missing GEMINI_API_KEY. Set it to enable Gemini generation.")

        resolved_model = model or self.default_model
        payload = self.post_json(
            (
                f"{self.base_url}/v1beta/models/"
                f"{parse.quote(resolved_model, safe='')}:generateContent"
            ),
            {
                "contents": [
                    {
                        "role": "user",
                        "parts": [{"text": prompt}],
                    }
                ]
            },
            {
                "Content-Type": "application/json",
                "x-goog-api-key": self.api_key,
            },
            "Gemini",
        )
        generated_text = extract_gemini_text(payload)
        if not generated_text:
            raise LLMClientError("Gemini returned an empty response payload.")
        return generated_text


class AnthropicClient(BaseHTTPClient):
    def __init__(self, api_key, base_url, default_model, api_version, max_tokens=2048, timeout=120):
        super().__init__(timeout=timeout)
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.default_model = default_model
        self.api_version = api_version
        self.max_tokens = max_tokens

    def generate(self, prompt, model=None):
        if not self.api_key:
            raise LLMClientError("Missing ANTHROPIC_API_KEY. Set it to enable Claude generation.")

        payload = self.post_json(
            f"{self.base_url}/v1/messages",
            {
                "model": model or self.default_model,
                "max_tokens": self.max_tokens,
                "messages": [
                    {
                        "role": "user",
                        "content": prompt,
                    }
                ],
            },
            {
                "Content-Type": "application/json",
                "x-api-key": self.api_key,
                "anthropic-version": self.api_version,
            },
            "Claude",
        )
        generated_text = extract_anthropic_text(payload)
        if not generated_text:
            raise LLMClientError("Claude returned an empty response payload.")
        return generated_text

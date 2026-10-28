"""
Safe Home AI — პროვაიდერის ადაპტერი. სისტემის დანარჩენი ნაწილი მხოლოდ `Provider.run(...)`-ს იცნობს, ამიტომ მოდელი/პროვაიდერი
`config.AI_PROVIDER` / `AI_MODEL`-ით იცვლება ისე, რომ `ai_service`/`ai_api` არ შეიცვალოს.

* `AnthropicProvider` — ოფიციალური `anthropic` SDK (იმპორტი ზარმაცია: პაკეტის გარეშეც მთელი CRM ჩვეულებრივად იტვირთება).
  გასაღები მხოლოდ `config.ANTHROPIC_API_KEY`-დან (Railway env). წაკითხვა-მხოლოდ ინსტრუმენტების ციკლი აქვე, ზღვრით (`max_steps`).
* `FakeProvider` — ტესტებისთვის (ქსელი/ხარჯი არ არის).
შეცდომები ერთ ტიპში (`ProviderError.kind`): timeout | rate_limit | unavailable | auth | bad_request | refusal | not_configured.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field

import config

log = logging.getLogger("safehome-ai-provider")

# $ / 1 მლნ ტოკენზე (input, output) — **შეფასებისთვის**; გადაამოწმეთ ოფიციალურ ფასებთან (config-ში გადაიწერება)
PRICES = {
    "claude-haiku-5-5": (0.10, 0.50),
    "claude-sonnet-5-5": (2.0, 10.0),
    "claude-sonnet-5": (2.0, 10.0),
    "claude-opus-5-5": (4.0, 20.0),
    "claude-opus-5": (5.0, 25.0),
}
DEFAULT_PRICE = (2.0, 10.0)


class ProviderError(Exception):
    def __init__(self, kind: str, msg: str = ""):
        super().__init__(msg or kind)
        self.kind = kind


@dataclass
class Completion:
    text: str
    tokens_in: int = 0
    tokens_out: int = 0
    cache_read: int = 0
    cache_write: int = 0
    model: str = ""
    stop_reason: str = ""
    tools_used: list = field(default_factory=list)


def price_for(model: str) -> tuple[float, float]:
    try:
        if config.AI_PRICE_IN_PER_MTOK and config.AI_PRICE_OUT_PER_MTOK:
            return float(config.AI_PRICE_IN_PER_MTOK), float(config.AI_PRICE_OUT_PER_MTOK)
    except ValueError:
        pass
    return PRICES.get(model, DEFAULT_PRICE)


def estimate_cost(model: str, tokens_in: int, tokens_out: int, cache_read: int = 0, cache_write: int = 0) -> float:
    """შეფასება: cache-ის წაკითხვა ≈ 0.1×, ჩაწერა ≈ 1.25× input-ფასზე. რეალური ხარჯი — პროვაიდერის ანგარიშში."""
    pin, pout = price_for(model)
    return round((tokens_in * pin + cache_read * pin * 0.1 + cache_write * pin * 1.25 + tokens_out * pout) / 1_000_000, 6)


class Provider:
    name = "base"
    model = ""

    def run(self, system: str, messages: list, tools: list | None, call_tool, max_tokens: int, timeout: float,
            max_steps: int = 4) -> Completion:
        raise NotImplementedError


class AnthropicProvider(Provider):
    name = "anthropic"

    def __init__(self, api_key: str, model: str, effort: str = "medium", client=None):
        self.model = model
        self.effort = effort if effort in ("low", "medium", "high") else "medium"
        self._client = client
        self._api_key = api_key

    def _cli(self):
        if self._client is None:
            try:
                import anthropic
            except ImportError as e:                                   # pragma: no cover
                raise ProviderError("not_configured", "anthropic პაკეტი არ არის დაინსტალირებული") from e
            self._client = anthropic.Anthropic(api_key=self._api_key)
        return self._client

    @staticmethod
    def _map(exc) -> ProviderError:
        import anthropic
        if isinstance(exc, anthropic.APITimeoutError):
            return ProviderError("timeout")
        if isinstance(exc, anthropic.RateLimitError):
            return ProviderError("rate_limit")
        if isinstance(exc, (anthropic.AuthenticationError, anthropic.PermissionDeniedError)):
            return ProviderError("auth")
        if isinstance(exc, anthropic.APIConnectionError):
            return ProviderError("unavailable")
        if isinstance(exc, anthropic.APIStatusError):
            return ProviderError("unavailable" if getattr(exc, "status_code", 500) >= 500 else "bad_request", str(getattr(exc, "message", exc))[:200])
        return ProviderError("unavailable", type(exc).__name__)

    def run(self, system, messages, tools, call_tool, max_tokens, timeout, max_steps=4) -> Completion:
        import anthropic
        client = self._cli().with_options(timeout=timeout, max_retries=1)
        msgs = list(messages)
        total = Completion(text="", model=self.model)
        for step in range(max_steps + 1):
            kw = dict(model=self.model, max_tokens=max_tokens, system=system, messages=msgs,
                      output_config={"effort": self.effort}, cache_control={"type": "ephemeral"})
            if tools and step < max_steps:
                kw["tools"] = tools
            try:
                resp = client.messages.create(**kw)
            except anthropic.APIError as e:
                raise self._map(e) from e
            u = resp.usage
            total.tokens_in += int(getattr(u, "input_tokens", 0) or 0)
            total.tokens_out += int(getattr(u, "output_tokens", 0) or 0)
            total.cache_read += int(getattr(u, "cache_read_input_tokens", 0) or 0)
            total.cache_write += int(getattr(u, "cache_creation_input_tokens", 0) or 0)
            total.stop_reason = str(resp.stop_reason or "")
            if resp.stop_reason == "refusal":
                raise ProviderError("refusal")
            if resp.stop_reason == "tool_use":
                if step >= max_steps:                               # ბოლო ნაბიჯზე ინსტრუმენტები აღარ გვეძლევა — ციკლი იჭრება
                    break
                msgs.append({"role": "assistant", "content": resp.content})
                results = []
                for b in resp.content:
                    if getattr(b, "type", "") == "tool_use":
                        total.tools_used.append(b.name)
                        try:
                            out, is_err = call_tool(b.name, dict(b.input or {})), False
                        except Exception as e:  # noqa: BLE001 — ინსტრუმენტის შეცდომა მოდელს ეუბნება, მოთხოვნას არ ანგრევს
                            log.warning("AI tool %s ჩავარდა: %s", b.name, type(e).__name__)
                            out, is_err = json.dumps({"error": "ინსტრუმენტი დროებით მიუწვდომელია"}, ensure_ascii=False), True
                        results.append({"type": "tool_result", "tool_use_id": b.id, "content": out, **({"is_error": True} if is_err else {})})
                msgs.append({"role": "user", "content": results})
                continue
            total.text = "".join(getattr(b, "text", "") for b in resp.content if getattr(b, "type", "") == "text")
            return total
        raise ProviderError("bad_request", "ინსტრუმენტების ციკლი ლიმიტს გადასცდა")


class FakeProvider(Provider):
    """ტესტებისთვის: `fn(system, messages, tools, call_tool) -> str | dict(text=, tokens_in=, tokens_out=, tools=[...])` ან ისვრის ProviderError-ს."""
    name = "fake"

    def __init__(self, fn, model: str = "claude-sonnet-5-5"):
        self.fn = fn
        self.model = model
        self.calls: list[dict] = []

    def run(self, system, messages, tools, call_tool, max_tokens, timeout, max_steps=4) -> Completion:
        self.calls.append({"system": system, "messages": messages, "tools": tools, "max_tokens": max_tokens, "timeout": timeout})
        r = self.fn(system, messages, tools, call_tool)
        if isinstance(r, str):
            r = {"text": r}
        return Completion(text=r.get("text", ""), tokens_in=r.get("tokens_in", 1200), tokens_out=r.get("tokens_out", 200),
                          model=self.model, stop_reason="end_turn", tools_used=list(r.get("tools", [])))


_provider: Provider | None = None
_built_for: tuple | None = None


def set_provider(p: Provider | None) -> None:
    global _provider, _built_for
    _provider, _built_for = p, None


def get_provider() -> Provider:
    global _provider, _built_for
    if _provider is not None and _built_for is None:
        return _provider                                              # ტესტში/ხელით ჩასმული
    key = (config.AI_PROVIDER, config.ANTHROPIC_API_KEY, config.AI_MODEL, config.AI_EFFORT)
    if _provider is not None and _built_for == key:
        return _provider
    if config.AI_PROVIDER != "anthropic":
        raise ProviderError("not_configured", f"უცნობი პროვაიდერი: {config.AI_PROVIDER}")
    if not config.ANTHROPIC_API_KEY:
        raise ProviderError("not_configured", "ANTHROPIC_API_KEY დაყენებული არ არის")
    try:
        import anthropic  # noqa: F401
    except ImportError:
        raise ProviderError("not_configured", "anthropic პაკეტი არ არის დაინსტალირებული (requirements.txt; საჭიროა Python ≥ 3.11)") from None
    _provider = AnthropicProvider(config.ANTHROPIC_API_KEY, config.AI_MODEL, config.AI_EFFORT)
    _built_for = key
    return _provider


def configured() -> bool:
    try:
        get_provider()
        return True
    except ProviderError:
        return False


def now_ms() -> float:
    return time.time() * 1000.0

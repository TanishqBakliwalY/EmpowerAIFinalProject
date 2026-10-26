"""Deterministic safety checks that run outside the model.

1. Input screen for untrusted client documents: strips hidden content (HTML comments, zero-width and
   bidi-control characters, script/style blocks) and flags text that tries to instruct the AI.
2. Spotlighting: untrusted text is wrapped in <client_document> tags so prompts can tell data from orders.
3. Output leak check: a client-facing document may not contain the prompt canary, salaries, internal
   cost rates, margins or other internal-only terms. Offending lines are redacted and the event logged.
4. A sliding-window rate limiter per client IP.
"""

from __future__ import annotations

import re
import time
import unicodedata
from collections import defaultdict, deque
from dataclasses import dataclass, field

from .config import PROMPT_CANARY

# ---------------------------------------------------------------------------- input screen

_HTML_COMMENT = re.compile(r"<!--(.*?)-->", re.DOTALL)
_HIDDEN_BLOCK = re.compile(r"<(script|style)\b[^>]*>(.*?)</\1\s*>", re.DOTALL | re.IGNORECASE)
_INVISIBLE = re.compile("[​‌‍⁠﻿‪-‮⁦-⁩]")

# Phrases that address the AI system rather than describe a software project: (kind, severity, pattern).
# "high" = clearly aimed at the AI; "warning" = could be an honest (if odd) client request.
INJECTION_PATTERNS: list[tuple[str, str, re.Pattern]] = [
    ("override", "high", re.compile(r"\b(ignore|disregard|forget|override)\b[^.\n]{0,40}\b(previous|prior|above|earlier|all|your)\b[^.\n]{0,20}\b(instructions?|rules|prompts?|guidelines)", re.I)),
    ("role_hijack", "high", re.compile(r"\b(you are now|act as|pretend to be|from now on you|switch to)\b[^.\n]{0,40}\b(mode|assistant|ai|model|system|admin|developer)\b", re.I)),
    ("mode_switch", "high", re.compile(r"\b(maintenance|developer|debug|god|jailbreak|dan)\s+mode\b", re.I)),
    ("prompt_exfiltration", "high", re.compile(r"\b(system prompt|your (instructions|prompt|rules)|hidden instructions|initial prompt)\b", re.I)),
    ("concealment", "high", re.compile(r"\b(do not|don't|never)\s+(mention|tell|reveal|disclose)\b[^.\n]{0,40}\b(this|anyone|note|instruction)", re.I)),
    ("ai_addressed", "high", re.compile(r"\b(note|message|instruction)s?\s+(to|for)\s+(the\s+)?(ai|assistant|llm|model|bot|system)\b", re.I)),
    ("price_manipulation", "warning", re.compile(r"\b(set|make|change)\b[^.\n]{0,30}\b(price|quote|total|margin|discount|rate)s?\b[^.\n]{0,20}\b(to|=)\b", re.I)),
    ("internal_data_request", "warning", re.compile(r"\b(internal (hourly )?(cost|rates?)|salar(y|ies)|ctc|cost to company|margin floor|your margins?)\b", re.I)),
]


@dataclass
class Finding:
    kind: str
    severity: str  # "info" | "warning" | "high"
    message: str
    snippet: str = ""

    def to_dict(self) -> dict:
        return {"kind": self.kind, "severity": self.severity, "message": self.message, "snippet": self.snippet}


@dataclass
class ScreenResult:
    clean_text: str
    findings: list[Finding] = field(default_factory=list)

    @property
    def injection_suspected(self) -> bool:
        return any(f.severity == "high" for f in self.findings)


def _clip(s: str, n: int = 220) -> str:
    s = " ".join(s.split())
    return s if len(s) <= n else s[: n - 1] + "…"


def screen_untrusted(text: str) -> ScreenResult:
    """Clean a client-supplied document and report anything that looks like an attack."""
    findings: list[Finding] = []
    text = unicodedata.normalize("NFKC", text)

    invisible = _INVISIBLE.findall(text)
    if invisible:
        findings.append(Finding("hidden_characters", "warning",
                                f"Removed {len(invisible)} invisible/bidi control characters that can hide text."))
        text = _INVISIBLE.sub("", text)

    for m in _HIDDEN_BLOCK.finditer(text):
        findings.append(Finding("hidden_block", "high", f"Removed a hidden <{m.group(1)}> block.", _clip(m.group(2))))
    text = _HIDDEN_BLOCK.sub(" ", text)

    for m in _HTML_COMMENT.finditer(text):
        body = m.group(1)
        sev = "high" if any(p.search(body) for _, _, p in INJECTION_PATTERNS) else "warning"
        findings.append(Finding("hidden_comment", sev,
                                "Removed hidden HTML comment" + (" containing instructions aimed at the AI." if sev == "high" else "."),
                                _clip(body)))
    text = _HTML_COMMENT.sub(" ", text)

    # Visible text that addresses the AI: keep it (it may be a clumsy but honest request) but flag it
    # and tell every agent to treat it as untrusted data.
    for line in text.splitlines():
        for kind, sev, pat in INJECTION_PATTERNS:
            if pat.search(line):
                msg = ("Visible text tries to instruct the AI; treated as data only." if sev == "high"
                       else "Unusual request in the document (pricing/internal data); agents treat it as data only.")
                findings.append(Finding(kind, sev, msg, _clip(line)))
                break

    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    return ScreenResult(clean_text=text, findings=findings)


REDACTED_LINE = "[Removed by Empower's safety screen: text addressed to an AI system]"


def redact_ai_directed_lines(text: str) -> tuple[str, int]:
    """A client document is a request for work: a line that addresses an AI system is never a legitimate ask, so it is
    removed before any agent reads it (the model provider's own filter would also reject the whole prompt)."""
    lines, removed = [], 0
    for line in text.splitlines():
        if any(sev == "high" and pat.search(line) for _, sev, pat in INJECTION_PATTERNS):
            lines.append(REDACTED_LINE)
            removed += 1
        else:
            lines.append(line)
    return "\n".join(lines), removed


def is_content_filter(exc: BaseException) -> bool:
    """True when the model provider refused the prompt with its own safety filter (Azure content management)."""
    return "content_filter" in str(getattr(exc, "body", "") or exc)


def spotlight(text: str, label: str = "client_document") -> str:
    """Wrap untrusted text so prompts can refer to it as data. Neutralises fake closing tags."""
    safe = re.sub(rf"</?\s*{label}\s*>", "[tag removed]", text, flags=re.I)
    return f"<{label}>\n{safe}\n</{label}>"


# ---------------------------------------------------------------------------- output leak check

_LEAK_TERMS = re.compile(
    r"\b(salar(y|ies)|ctc|cost to company|internal (hourly )?(cost|rate)s?|cost rates?|gross margin|our margin|margin floor|"
    r"margin of \d+|\d+(\.\d+)?\s*% margin|inr|lakhs?|system prompt)\b|₹",
    re.I,
)


@dataclass
class LeakResult:
    text: str
    findings: list[Finding] = field(default_factory=list)

    @property
    def blocked(self) -> bool:
        return any(f.severity == "high" for f in self.findings)


_CLIENT_CURRENCY_BEFORE = re.compile(r"(\$|€|£|USD|EUR|GBP|US\$)\s?[~≈]?$", re.I)
_CLIENT_CURRENCY_AFTER = re.compile(r"^\s?(k\b)?\s?(USD|EUR|GBP)\b", re.I)
# Second number of a client-currency range: "USD 60,000–80,000", "$60,000 to $80,000".
_CLIENT_RANGE_BEFORE = re.compile(r"(\$|€|£|USD|EUR|GBP|US\$)\s?\d[\d,.]*\s?k?\s?(-|–|—|to)\s?(\$|€|£)?\s?$", re.I)
_SCALED_AMOUNT = re.compile(r"(\d+(?:\.\d+)?)\s?(?:(?:-|–|—|to)\s?\$?(\d+(?:\.\d+)?)\s?)?([km])\b", re.I)


def _client_numbers(text: str) -> set[str]:
    """Numbers the client wrote, in the forms a proposal may print them: "$60-80k" -> 60,000 and 80,000."""
    out: set[str] = set()
    for m in _SCALED_AMOUNT.finditer(text):
        scale = 1_000 if m.group(3).lower() == "k" else 1_000_000
        for v in filter(None, (m.group(1), m.group(2))):
            n = float(v) * scale
            out |= {f"{n:,.0f}", f"{n:.0f}"}
    return out


def _leaks_number(line: str, numbers: set[str], allowed: set[str]) -> bool:
    """An internal figure appears in the line, other than as a client-currency amount or a number the client wrote."""
    for n in numbers:
        if n in allowed:
            continue
        for m in re.finditer(rf"(?<![\d,.]){re.escape(n)}(?![\d,]*\d)", line):
            before, after = line[max(0, m.start() - 6):m.start()], line[m.end():m.end() + 6]
            wide = line[max(0, m.start() - 30):m.start()]
            if (_CLIENT_CURRENCY_BEFORE.search(before) or _CLIENT_CURRENCY_AFTER.search(after)
                    or _CLIENT_RANGE_BEFORE.search(wide)):
                continue  # "$80,000" / "80,000 USD" is a client-side amount, not a rupee salary
            return True
    return False


def leak_check(text: str, sensitive_numbers: set[str] | None = None, allowed_text: str = "") -> LeakResult:
    """Redact lines of a client-facing document that expose internal data.

    `allowed_text` is what the client wrote themselves: numbers that appear there (their budget, say) are not leaks.
    """
    findings: list[Finding] = []
    out_lines = []
    numbers = {n for n in (sensitive_numbers or set()) if len(n.replace(",", "")) >= 5}
    client = _client_numbers(allowed_text) if allowed_text else set()
    allowed = {n for n in numbers if n in allowed_text or n in client}
    for line in text.splitlines():
        reason = None
        if PROMPT_CANARY in line:
            reason = ("prompt_leak", "System-prompt canary found: the model tried to reveal its instructions.")
        elif _LEAK_TERMS.search(line):
            reason = ("internal_terms", f"Internal-only term in client document: '{_LEAK_TERMS.search(line).group(0)}'.")
        elif numbers and _leaks_number(line, numbers, allowed):
            reason = ("internal_numbers", "An employee's internal cost figure appeared in the client document.")
        if reason:
            findings.append(Finding(reason[0], "high", reason[1], _clip(line)))
            out_lines.append("> [Redacted by Empower leak guard: internal information removed]")
        else:
            out_lines.append(line)
    return LeakResult(text="\n".join(out_lines), findings=findings)


# ---------------------------------------------------------------------------- rate limiting


class RateLimiter:
    def __init__(self, max_events: int, window_seconds: int) -> None:
        self.max_events = max_events
        self.window = window_seconds
        self._hits: dict[str, deque[float]] = defaultdict(deque)

    def check(self, key: str) -> int | None:
        """Record one event for `key`. Returns seconds to wait if over the limit, else None."""
        now = time.monotonic()
        q = self._hits[key]
        while q and q[0] <= now - self.window:
            q.popleft()
        if len(q) >= self.max_events:
            return int(q[0] + self.window - now) + 1
        q.append(now)
        return None

    def wait_seconds(self, key: str) -> int | None:
        """Seconds to wait if `key` is over the limit, without recording an event."""
        now = time.monotonic()
        q = self._hits[key]
        while q and q[0] <= now - self.window:
            q.popleft()
        return int(q[0] + self.window - now) + 1 if len(q) >= self.max_events else None

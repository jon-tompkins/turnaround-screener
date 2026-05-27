"""Analyst — runs new tickers through Claude for structured analysis.

Uses Claude Sonnet 4.6 by default (cheaper for per-ticker work). Opus 4.7 is
reserved for retrospectives where deep reasoning matters more than cost.

The prompt enforces a strict JSON schema so downstream code can rely on
specific fields existing.
"""
import json
import os
from typing import Optional

from anthropic import Anthropic

from config import settings


SYSTEM_PROMPT = """You are a senior equity analyst specializing in turnaround situations.

You receive a dossier on a stock that has just passed a technical screen. The
core screen requires price < 50% of the 200-week MA (a ~50%+ multi-year
drawdown). The dossier's `screen_mode` field tells you which leg of the screen
the name passed:

  • "recovering" — price is already above the 200-day MA and not too far above.
    The thesis: the turnaround has started; judge whether the move continues.
    Catalysts and momentum matter most.

  • "basing" — price is still below the 200-day MA but close to crossing,
    with flat-to-positive 30-day momentum and holding above the 100-day MA.
    The thesis: the bottom may be in but it hasn't broken out yet. Time
    horizon is longer; entry is cheaper but risk of re-breakdown is higher.

You MUST respond with valid JSON only — no preamble, no commentary, no
markdown code fences. The JSON must match the schema below exactly.

Be honest and skeptical. Most names that pass technical screens are NOT good
trades. Reserve high conviction scores (8+) for setups with multiple
catalysts, real businesses, and identifiable asymmetric payoffs."""


SCHEMA_PROMPT = """Output schema (return JSON matching exactly this shape):

{
  "ticker": str,
  "company_name": str,
  "sector": str,
  "industry": str,
  "turnaround_reason": str,         // 1-2 sentences on what beat it down and why it might recover
  "bullish_points": [str],          // 3-5 concrete positives
  "bearish_points": [str],          // 3-5 concrete risks
  "catalyst": str,                  // The specific event that could drive the move
  "catalyst_timing": str,           // When (e.g. "Q2 2026 earnings", "FDA decision by July")
  "options_liquid": bool,           // Are options usable for this trade?
  "conviction_score": int,          // 1-10. 8+ = high conviction. Most should be 4-7.
  "suggested_trade": str,           // Specific: "Spot only", "Jan 2027 $15 calls", "Bear put spread", etc.
  "key_risk": str,                  // The one thing most likely to invalidate the thesis
  "estimated_upside_pct": int,      // Realistic % upside in 3-12 months if thesis plays out
  "estimated_downside_pct": int,    // Realistic % downside if thesis fails
  "would_skip_if": str              // Conditions that would make you pass on this name
}"""


def _build_user_prompt(enriched_data: dict) -> str:
    """Construct the user message containing the enrichment dossier."""
    return f"""{SCHEMA_PROMPT}

Now analyze this ticker. Dossier follows:

{json.dumps(enriched_data, indent=2, default=str)}

Remember: JSON only, matching the schema exactly. No code fences."""


def analyze_ticker(enriched_data: dict, model: Optional[str] = None) -> dict:
    """Send enriched data to Claude, get structured analysis back.

    Returns the parsed JSON dict. Raises on parse failure (so we know to
    inspect the raw output and tighten the prompt).
    """
    if not settings.ANTHROPIC_API_KEY:
        raise RuntimeError("ANTHROPIC_API_KEY not set in environment.")

    model = model or settings.ANALYST_MODEL
    client = Anthropic(api_key=settings.ANTHROPIC_API_KEY)

    response = client.messages.create(
        model=model,
        max_tokens=2000,
        system=SYSTEM_PROMPT,
        messages=[
            {"role": "user", "content": _build_user_prompt(enriched_data)}
        ],
    )

    # Pull text from the first content block
    raw = response.content[0].text.strip()

    # Defensive: strip markdown fences if Claude included them despite instructions
    if raw.startswith("```"):
        lines = raw.split("\n")
        raw = "\n".join(lines[1:-1] if lines[-1].startswith("```") else lines[1:])

    try:
        result = json.loads(raw)
    except json.JSONDecodeError as e:
        # Save the broken output for inspection
        debug_path = settings.DATA_DIR / f"failed_analysis_{enriched_data['ticker']}.txt"
        debug_path.write_text(raw)
        raise RuntimeError(
            f"Failed to parse Claude response for {enriched_data['ticker']}. "
            f"Raw output saved to {debug_path}. Error: {e}"
        )

    # Track approximate cost
    usage = response.usage
    # Sonnet 4.6 pricing as of writing; adjust if model changes
    cost_estimate = (
        usage.input_tokens * 3 / 1_000_000 +
        usage.output_tokens * 15 / 1_000_000
    )
    result["_meta"] = {
        "model": model,
        "input_tokens": usage.input_tokens,
        "output_tokens": usage.output_tokens,
        "cost_estimate_usd": round(cost_estimate, 4),
    }

    return result

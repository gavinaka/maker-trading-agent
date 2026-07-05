"""Source-change observability plus mandatory full-session analysis.

The graph explains which conclusions a changed source can affect. It never
authorizes reusing analysis: every report recomputes the full analysis graph.
"""

from __future__ import annotations

from collections import deque


DEPENDENCIES: dict[str, set[str]] = {
    "source:blockbeats": {"feature:news", "feature:fundamentals"},
    "source:fedwatch": {"feature:macro"},
    "source:farside_btc_etf": {"feature:spot_etf_flow"},
    "source:coinglass": {"feature:orderflow"},
    "source:exocharts": {"feature:orderflow_confirmation"},
    "source:tradingview_1d": {"feature:chart_1d", "feature:liquidity"},
    "source:tradingview_4h": {"feature:chart_4h", "feature:liquidity"},
    "source:tradingview_1h": {"feature:chart_1h", "feature:liquidity"},
    "source:tradingview_15m": {"feature:chart_15m", "feature:liquidity"},
    "source:liqheatmap": {"feature:liquidity_confirmation"},
    # Notion actual positions are post-lock operational facts only. They must
    # never reach analysis features, scores, win rate, or Maker/main decisions.
    "source:notion_positions": set(),
    "source:notion_gate": {"decision:session"},
    "feature:news": {"feature:fundamentals"},
    "feature:macro": {"feature:fundamentals", "score:winrate"},
    "feature:fundamentals": {
        "decision:main_account",
        "decision:maker",
        "decision:cannot_do",
    },
    "feature:orderflow_confirmation": {"feature:orderflow"},
    "feature:spot_etf_flow": {
        "feature:fundamentals",
        "feature:liquidity_confirmation",
        "score:winrate",
    },
    "feature:orderflow": {"score:orderflow", "score:winrate"},
    "feature:chart_1d": {"score:chart", "feature:trend_regime"},
    "feature:chart_4h": {"score:chart", "feature:trend_regime"},
    "feature:chart_1h": {"score:chart", "feature:trend_regime"},
    "feature:chart_15m": {"score:chart", "feature:entry_location"},
    "feature:liquidity_confirmation": {"feature:liquidity"},
    "feature:liquidity": {"score:chart", "feature:entry_location"},
    "feature:trend_regime": {
        "decision:main_account",
        "decision:maker",
        "score:winrate",
    },
    "feature:entry_location": {"score:winrate", "decision:maker"},
    "score:orderflow": {"score:total", "decision:maker", "decision:cannot_do"},
    "score:chart": {"score:total", "score:winrate"},
    "score:total": {"decision:maker"},
    "score:winrate": {"decision:maker"},
    "decision:main_account": {"output:report"},
    "decision:maker": {"output:report"},
    "decision:cannot_do": {"output:report"},
    "decision:session": {"output:report"},
}

SESSION_OUTPUT_NODES = {"decision:session", "output:report"}
ANALYSIS_ASSURANCE_NODES = {
    "validation:five_sources",
    "validation:six_sources",
    "transcription:blockbeats",
    "transcription:coinglass",
    "transcription:exocharts",
    "transcription:fedwatch",
    "transcription:farside_btc_etf",
    "transcription:tradingview",
    "analysis:spot_etf_flow_confirmation",
    "analysis:market_structure",
    "analysis:cross_source_synthesis",
    "analysis:volatility_regime",
    "analysis:liquidity_structure",
    "analysis:risk",
    "analysis:scenarios",
    "output:report_writing",
    "output:quality_review",
}


def affected_nodes(changed_sources: set[str]) -> set[str]:
    """Return the transitive source-impact closure for diagnostics only."""
    seeds = {f"source:{source}" for source in changed_sources}
    result: set[str] = set()
    queue = deque(seeds)
    seen = set(seeds)
    while queue:
        node = queue.popleft()
        for downstream in DEPENDENCIES.get(node, set()):
            if downstream not in result:
                result.add(downstream)
            if downstream not in seen:
                seen.add(downstream)
                queue.append(downstream)
    return result


def all_recomputable_nodes() -> set[str]:
    nodes = set(SESSION_OUTPUT_NODES)
    for source, downstream in DEPENDENCIES.items():
        if not source.startswith("source:"):
            nodes.add(source)
        nodes.update(downstream)
    return nodes


def required_analysis_nodes(slot: str | None = None) -> set[str]:
    """Return every node that must be independently recomputed per report."""
    return all_recomputable_nodes() | ANALYSIS_ASSURANCE_NODES


def required_post_lock_nodes(slot: str) -> set[str]:
    """Return work that is allowed only after the independent analysis lock."""
    nodes = {"post_lock:prior_plan_continuity"}
    if slot == "evening":
        nodes.add("post_lock:evening_independent_review")
    return nodes


ALWAYS_RECOMPUTE = required_analysis_nodes()

"""Performance aggregation helpers for agent runs."""


def build_performance_entry(
    *,
    quality_score: float,
    response_time_ms: int,
    revision_count: int,
    contribution_chars: int,
    total_chars: int,
    token_usage: int,
    error_count: int = 0,
) -> dict:
    contribution_score = 0.0 if total_chars <= 0 else contribution_chars / total_chars
    revision_rate = min(1.0, revision_count / 2) if revision_count > 0 else 0.0
    return {
        "quality_score": round(quality_score, 4),
        "response_time_ms": response_time_ms,
        "revision_rate": round(revision_rate, 4),
        "contribution_score": round(contribution_score, 4),
        "token_usage": token_usage,
        "error_count": error_count,
    }

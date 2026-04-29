from fastapi import APIRouter, Depends
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.agent import Agent, AgentPerformance
from app.models.database import get_db

router = APIRouter(tags=["performance"])


@router.get("/performance")
async def get_performance_data(db: Session = Depends(get_db)) -> dict:
    rows = (
        db.query(
            Agent.id.label("agent_id"),
            Agent.name.label("agent_name"),
            func.avg(AgentPerformance.quality_score).label("avg_quality"),
            func.avg(AgentPerformance.response_time_ms).label("avg_response_time_ms"),
            func.avg(AgentPerformance.revision_rate).label("avg_revision_rate"),
            func.avg(AgentPerformance.contribution_score).label("avg_contribution"),
            func.sum(AgentPerformance.token_usage).label("total_tokens"),
            func.sum(AgentPerformance.error_count).label("total_errors"),
        )
        .join(AgentPerformance, AgentPerformance.agent_id == Agent.id, isouter=True)
        .group_by(Agent.id, Agent.name)
        .all()
    )

    leaderboard = []
    for row in rows:
        quality = float(row.avg_quality or 0)
        response = float(row.avg_response_time_ms or 0)
        revision = float(row.avg_revision_rate or 0)
        contribution = float(row.avg_contribution or 0)
        normalized_speed = max(0.0, 1.0 - min(response / 10000.0, 1.0))
        composite = (quality * 0.4) + (normalized_speed * 0.2) + ((1.0 - revision) * 0.2) + (contribution * 0.2)
        leaderboard.append(
            {
                "agent_id": row.agent_id,
                "agent_name": row.agent_name,
                "quality_score": round(quality, 4),
                "response_time_ms": round(response, 2),
                "revision_rate": round(revision, 4),
                "contribution_score": round(contribution, 4),
                "token_usage": int(row.total_tokens or 0),
                "error_count": int(row.total_errors or 0),
                "composite_score": round(composite, 4),
            }
        )
    leaderboard.sort(key=lambda item: item["composite_score"], reverse=True)

    return {
        "leaderboard": leaderboard,
        "metrics": {
            "quality": [{"agent_id": row["agent_id"], "value": row["quality_score"]} for row in leaderboard],
            "response_time": [{"agent_id": row["agent_id"], "value": row["response_time_ms"]} for row in leaderboard],
            "revision_rate": [{"agent_id": row["agent_id"], "value": row["revision_rate"]} for row in leaderboard],
            "token_usage": [{"agent_id": row["agent_id"], "value": row["token_usage"]} for row in leaderboard],
        },
    }

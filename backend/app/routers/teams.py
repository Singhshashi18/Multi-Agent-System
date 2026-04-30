import json
from pathlib import Path
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.agent import Agent, team_agents
from app.models.database import get_db
from app.models.schemas import TeamCreateRequest, TeamResponse, TeamUpdateRequest
from app.models.team import Team

router = APIRouter(tags=["teams"])


def _normalize_agent_ids(agent_ids: list[str]) -> list[str]:
    """Trim, dedupe, and preserve order for incoming team agent IDs."""
    normalized: list[str] = []
    for raw in agent_ids:
        cleaned = (raw or "").strip()
        if cleaned and cleaned not in normalized:
            normalized.append(cleaned)
    return normalized


@router.get("/templates")
async def get_team_templates() -> list[dict]:
    file_path = Path(__file__).resolve().parents[1] / "data" / "team_templates.json"
    with file_path.open("r", encoding="utf-8") as f:
        return json.load(f)


@router.get("/teams")
async def list_teams(db: Session = Depends(get_db)) -> list[TeamResponse]:
    teams = db.query(Team).order_by(Team.created_at.desc()).all()
    result: list[TeamResponse] = []
    for team in teams:
        rows = db.execute(select(team_agents.c.agent_id).where(team_agents.c.team_id == team.id)).all()
        agent_ids = [row[0] for row in rows]
        result.append(
            TeamResponse(
                id=team.id,
                name=team.name,
                pattern=team.pattern,
                description=team.description,
                agent_ids=agent_ids,
                config=team.config or {},
            )
        )
    return result


@router.post("/teams")
async def create_team(payload: TeamCreateRequest, db: Session = Depends(get_db)) -> TeamResponse:
    team_id = payload.id or str(uuid.uuid4())
    if db.query(Team).filter(Team.id == team_id).first():
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Team ID already exists")

    clean_agent_ids = _normalize_agent_ids(payload.agent_ids)
    if not clean_agent_ids:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Team must include at least one agent")
    found_count = db.query(Agent).filter(Agent.id.in_(clean_agent_ids)).count()
    if found_count != len(clean_agent_ids):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="One or more agent IDs do not exist")

    team = Team(
        id=team_id,
        name=payload.name,
        pattern=payload.pattern,
        description=payload.description,
        config={**(payload.config or {}), "max_revisions": 0},
    )
    db.add(team)
    db.flush()
    for agent_id in clean_agent_ids:
        db.execute(team_agents.insert().values(team_id=team_id, agent_id=agent_id))
    db.commit()
    rows = db.execute(select(team_agents.c.agent_id).where(team_agents.c.team_id == team.id)).all()
    mapped_ids = [row[0] for row in rows]
    return TeamResponse(
        id=team.id,
        name=team.name,
        pattern=team.pattern,
        description=team.description,
        agent_ids=mapped_ids,
        config=team.config or {},
    )


@router.get("/teams/{team_id}")
async def get_team(team_id: str, db: Session = Depends(get_db)) -> TeamResponse:
    team = db.query(Team).filter(Team.id == team_id).first()
    if not team:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Team not found")
    rows = db.execute(select(team_agents.c.agent_id).where(team_agents.c.team_id == team.id)).all()
    agent_ids = [row[0] for row in rows]
    return TeamResponse(
        id=team.id,
        name=team.name,
        pattern=team.pattern,
        description=team.description,
        agent_ids=agent_ids,
        config=team.config or {},
    )


@router.put("/teams/{team_id}")
async def update_team(team_id: str, payload: TeamUpdateRequest, db: Session = Depends(get_db)) -> TeamResponse:
    team = db.query(Team).filter(Team.id == team_id).first()
    if not team:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Team not found")

    updates = payload.model_dump(exclude_unset=True)
    agent_ids = updates.pop("agent_ids", None)

    for field_name, field_value in updates.items():
        if field_name == "config" and isinstance(field_value, dict):
            field_value = {**field_value, "max_revisions": 0}
        setattr(team, field_name, field_value)

    if agent_ids is not None:
        clean_agent_ids = _normalize_agent_ids(agent_ids)
        if not clean_agent_ids:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Team must include at least one agent")
        found_count = db.query(Agent).filter(Agent.id.in_(clean_agent_ids)).count()
        if found_count != len(clean_agent_ids):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="One or more agent IDs do not exist")
        db.execute(team_agents.delete().where(team_agents.c.team_id == team_id))
        for agent_id in clean_agent_ids:
            db.execute(team_agents.insert().values(team_id=team_id, agent_id=agent_id))

    db.commit()
    rows = db.execute(select(team_agents.c.agent_id).where(team_agents.c.team_id == team.id)).all()
    current_agent_ids = [row[0] for row in rows]
    return TeamResponse(
        id=team.id,
        name=team.name,
        pattern=team.pattern,
        description=team.description,
        agent_ids=current_agent_ids,
        config=team.config or {},
    )


@router.delete("/teams/{team_id}")
async def delete_team(team_id: str, db: Session = Depends(get_db)) -> dict[str, str]:
    team = db.query(Team).filter(Team.id == team_id).first()
    if not team:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Team not found")
    db.delete(team)
    db.commit()
    return {"message": "Team deleted"}

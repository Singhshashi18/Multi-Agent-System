import asyncio
import json
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter
from fastapi import Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.models.agent import Agent, AgentPerformance, team_agents
from app.models.database import SessionLocal, get_db
from app.models.schemas import DebateRunRequest, TaskCompareRequest, TaskCreateRequest, TaskMessageResponse, TaskResponse, TaskTimelineResponse
from app.models.task import Task, TaskMessage, TaskTimelineEvent
from app.models.team import Team
from app.services.langgraph.debate_graph import run_debate_workflow_stream
from app.services.langgraph.supervisor import run_supervisor_workflow_stream
from app.services.performance_tracker import build_performance_entry


router = APIRouter(tags=["tasks"])
TASK_STALL_TIMEOUT_SECONDS = 180


def _to_task_response(task: Task) -> TaskResponse:
    return TaskResponse(
        id=task.id,
        team_id=task.team_id,
        framework=task.framework,
        task_description=task.task_description,
        status=task.status,
        current_phase=task.current_phase,
        final_output=task.final_output,
        metadata=task.metadata_json or {},
    )


def _mark_task_stalled_if_needed(db: Session, task: Task) -> Task:
    if task.status != "running":
        return task
    task_mode = ((task.metadata_json or {}).get("mode") or "").lower()
    timeout_seconds = 420 if task_mode == "debate" else TASK_STALL_TIMEOUT_SECONDS
    latest_event = (
        db.query(TaskTimelineEvent)
        .filter(TaskTimelineEvent.task_id == task.id)
        .order_by(TaskTimelineEvent.id.desc())
        .first()
    )
    latest_message = (
        db.query(TaskMessage)
        .filter(TaskMessage.task_id == task.id)
        .order_by(TaskMessage.id.desc())
        .first()
    )
    reference_time = None
    event_time = latest_event.created_at if latest_event and latest_event.created_at else None
    message_time = latest_message.created_at if latest_message and latest_message.created_at else None
    if event_time and message_time:
        reference_time = max(event_time, message_time)
    elif event_time:
        reference_time = event_time
    elif message_time:
        reference_time = message_time
    else:
        reference_time = task.updated_at or task.created_at
    if not reference_time:
        return task
    if reference_time.tzinfo is None:
        reference_time = reference_time.replace(tzinfo=timezone.utc)
    if datetime.now(timezone.utc) - reference_time > timedelta(seconds=timeout_seconds):
        task.status = "failed"
        task.current_phase = "timeout"
        task.final_output = "Execution timed out. Please retry."
        db.commit()
        db.refresh(task)
    return task


async def _execute_task_async(task_id: str, team_id: str, task_description: str, framework: str) -> None:
    db = SessionLocal()
    try:
        task = db.query(Task).filter(Task.id == task_id).first()
        if not task:
            return
        task.status = "running"
        task.current_phase = "delegation"
        db.commit()

        if framework != "langgraph":
            task.status = "failed"
            task.current_phase = "unsupported_framework"
            task.final_output = "Only langgraph runtime is active currently."
            db.commit()
            return

        agent_rows = (
            db.query(Agent)
            .join(team_agents, team_agents.c.agent_id == Agent.id)
            .filter(team_agents.c.team_id == team_id)
            .all()
        )
        team_agents_payload = [
            {
                "id": row.id,
                "name": row.name,
                "role": row.role,
                "system_prompt": row.system_prompt,
                "tools": row.tools or [],
                "expertise_domain": row.expertise_domain,
                "communication_style": row.communication_style,
            }
            for row in agent_rows
        ]
        if not team_agents_payload:
            task.status = "failed"
            task.current_phase = "validation_error"
            task.final_output = "Selected team has no mapped agents."
            db.commit()
            return

        final_output = ""
        performance: list[dict] = []

        for chunk in run_supervisor_workflow_stream(task_description, team_agents_payload):
            task = db.query(Task).filter(Task.id == task_id).first()
            if task and task.status != "running":
                task.status = "running"
            if "timeline_event" in chunk:
                ev = chunk["timeline_event"]
                db.add(
                    TaskTimelineEvent(
                        task_id=task_id,
                        agent_name=ev["agent_name"],
                        event_type=ev["event_type"],
                        description=ev["description"],
                        metadata_json=ev.get("metadata", {}),
                    )
                )
                if task:
                    task.current_phase = (ev.get("event_type", "running") or "running").lower()
            if "message" in chunk:
                msg = chunk["message"]
                db.add(
                    TaskMessage(
                        task_id=task_id,
                        from_agent=msg["from_agent"],
                        to_agent=msg["to_agent"],
                        message_type=msg["message_type"],
                        content=msg["content"],
                    )
                )
            if chunk.get("done"):
                final_output = chunk.get("final_output", "")
                performance = chunk.get("performance", [])
                if task:
                    task.current_phase = "finalizing"
            db.commit()
            await asyncio.sleep(0.15)

        for metric in performance:
            db.add(
                AgentPerformance(
                    agent_id=metric["agent_id"],
                    task_id=task_id,
                    quality_score=metric["quality_score"],
                    response_time_ms=metric["response_time_ms"],
                    revision_rate=metric["revision_rate"],
                    contribution_score=metric["contribution_score"],
                    token_usage=metric["token_usage"],
                    error_count=metric["error_count"],
                )
            )
        task = db.query(Task).filter(Task.id == task_id).first()
        if task:
            task.final_output = final_output
            task.status = "completed"
            task.current_phase = "done"
        db.commit()
    except Exception as exc:
        failed_task = db.query(Task).filter(Task.id == task_id).first()
        if failed_task:
            failed_task.status = "failed"
            failed_task.current_phase = "error"
            failed_task.final_output = f"Execution failed: {exc}"
            db.commit()
    finally:
        db.close()


def _pick_debate_agents(agent_rows: list[Agent]) -> tuple[Agent | None, Agent | None, Agent | None]:
    def _find_by_keywords(keywords: tuple[str, ...], used: set[str]) -> Agent | None:
        for row in agent_rows:
            text = f"{row.name} {row.role}".lower()
            if row.id in used:
                continue
            if any(keyword in text for keyword in keywords):
                used.add(row.id)
                return row
        return None

    used: set[str] = set()
    pro = _find_by_keywords(("pro", "advocate"), used)
    con = _find_by_keywords(("con", "critic"), used)
    judge = _find_by_keywords(("judge", "moderator"), used)

    remaining = [row for row in agent_rows if row.id not in used]
    if not pro and remaining:
        pro = remaining.pop(0)
    if not con and remaining:
        con = remaining.pop(0)
    if not judge and remaining:
        judge = remaining.pop(0)
    return pro, con, judge


async def _execute_debate_async(task_id: str, team_id: str, task_description: str, rounds: int, framework: str) -> None:
    db = SessionLocal()
    try:
        task = db.query(Task).filter(Task.id == task_id).first()
        if not task:
            return
        task.status = "running"
        task.current_phase = "debate_round_1"
        db.commit()

        if framework != "langgraph":
            task.status = "failed"
            task.current_phase = "unsupported_framework"
            task.final_output = "Only langgraph runtime is active currently."
            db.commit()
            return

        agent_rows = (
            db.query(Agent)
            .join(team_agents, team_agents.c.agent_id == Agent.id)
            .filter(team_agents.c.team_id == team_id)
            .all()
        )
        pro, con, judge = _pick_debate_agents(agent_rows)
        if not pro or not con or not judge:
            task.status = "failed"
            task.current_phase = "validation_error"
            task.final_output = "Debate run requires at least 3 team agents (Pro, Con, Judge)."
            db.commit()
            return

        final_output = ""
        transcript: list[dict] = []
        debate_metrics: dict[str, dict[str, int | float]] = {
            pro.id: {"output_length": 0, "token_usage": 0, "message_count": 0, "quality_score": 0.74},
            con.id: {"output_length": 0, "token_usage": 0, "message_count": 0, "quality_score": 0.74},
            judge.id: {"output_length": 0, "token_usage": 0, "message_count": 0, "quality_score": 0.78},
        }
        name_to_agent_id = {
            pro.name: pro.id,
            con.name: con.id,
            judge.name: judge.id,
        }
        for chunk in run_debate_workflow_stream(
            topic=task_description,
            pro_agent_name=pro.name,
            con_agent_name=con.name,
            judge_agent_name=judge.name,
            rounds=rounds,
        ):
            task = db.query(Task).filter(Task.id == task_id).first()
            if "timeline_event" in chunk:
                ev = chunk["timeline_event"]
                db.add(
                    TaskTimelineEvent(
                        task_id=task_id,
                        agent_name=ev["agent_name"],
                        event_type=ev["event_type"],
                        description=ev["description"],
                        metadata_json=ev.get("metadata", {}),
                    )
                )
                if task:
                    event_type = (ev.get("event_type", "running") or "running").lower()
                    if event_type == "debate_round":
                        side = (ev.get("metadata", {}) or {}).get("side", "")
                        round_no = (ev.get("metadata", {}) or {}).get("round", "")
                        task.current_phase = f"debate_{side}_{round_no}"
                    elif event_type == "judge_verdict":
                        task.current_phase = "judge_verdict"
            if "message" in chunk:
                msg = chunk["message"]
                db.add(
                    TaskMessage(
                        task_id=task_id,
                        from_agent=msg["from_agent"],
                        to_agent=msg["to_agent"],
                        message_type=msg["message_type"],
                        content=msg["content"],
                    )
                )
                from_agent = msg.get("from_agent", "")
                metric_agent_id = name_to_agent_id.get(from_agent)
                if metric_agent_id and metric_agent_id in debate_metrics:
                    content = str(msg.get("content", "") or "")
                    token_estimate = max(40, len(content) // 3)
                    debate_metrics[metric_agent_id]["output_length"] = int(debate_metrics[metric_agent_id]["output_length"]) + len(content)
                    debate_metrics[metric_agent_id]["token_usage"] = int(debate_metrics[metric_agent_id]["token_usage"]) + token_estimate
                    debate_metrics[metric_agent_id]["message_count"] = int(debate_metrics[metric_agent_id]["message_count"]) + 1
            if chunk.get("done"):
                final_output = chunk.get("final_output", "")
                transcript = (chunk.get("metadata", {}) or {}).get("transcript", [])
                if task:
                    task.current_phase = "finalizing"
            db.commit()
            await asyncio.sleep(0.1)

        task = db.query(Task).filter(Task.id == task_id).first()
        if task:
            metadata = task.metadata_json or {}
            metadata["debate"] = {
                "rounds": rounds,
                "pro_agent_name": pro.name,
                "con_agent_name": con.name,
                "judge_agent_name": judge.name,
                "transcript": transcript,
            }
            task.metadata_json = metadata
            task.final_output = final_output
            task.status = "completed"
            task.current_phase = "done"
        total_chars = sum(int(item["output_length"]) for item in debate_metrics.values())
        for agent_id, metrics in debate_metrics.items():
            message_count = int(metrics["message_count"])
            # Debate has no revision loop currently; keep revision_count 0.
            perf = build_performance_entry(
                quality_score=float(metrics["quality_score"]),
                response_time_ms=max(120, message_count * 900),
                revision_count=0,
                contribution_chars=int(metrics["output_length"]),
                total_chars=total_chars,
                token_usage=int(metrics["token_usage"]),
                error_count=0,
            )
            db.add(
                AgentPerformance(
                    agent_id=agent_id,
                    task_id=task_id,
                    quality_score=perf["quality_score"],
                    response_time_ms=perf["response_time_ms"],
                    revision_rate=perf["revision_rate"],
                    contribution_score=perf["contribution_score"],
                    token_usage=perf["token_usage"],
                    error_count=perf["error_count"],
                )
            )
        db.commit()
    except Exception as exc:
        failed_task = db.query(Task).filter(Task.id == task_id).first()
        if failed_task:
            failed_task.status = "failed"
            failed_task.current_phase = "error"
            failed_task.final_output = f"Debate execution failed: {exc}"
            db.commit()
    finally:
        db.close()


@router.post("/tasks")
async def submit_task(payload: TaskCreateRequest, db: Session = Depends(get_db)) -> TaskResponse:
    team = db.query(Team).filter(Team.id == payload.team_id).first()
    if not team:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Team not found")

    task_id = str(uuid.uuid4())
    task = Task(
        id=task_id,
        team_id=payload.team_id,
        framework=payload.framework.value,
        task_description=payload.task_description,
        status="pending",
        current_phase="queued",
        final_output=None,
        metadata_json={"source": "api"},
    )
    db.add(task)
    db.flush()

    db.add(
        TaskTimelineEvent(
            task_id=task_id,
            agent_name="Supervisor",
            event_type="DELEGATION",
            description="Task submitted and queued for supervisor decomposition.",
            metadata_json={"framework": payload.framework.value},
        )
    )
    task.status = "queued"
    task.current_phase = "queued"

    db.commit()
    db.refresh(task)
    asyncio.create_task(_execute_task_async(task_id, payload.team_id, payload.task_description, payload.framework.value))

    return _to_task_response(task)


@router.post("/debates/run")
async def run_debate(payload: DebateRunRequest, db: Session = Depends(get_db)) -> TaskResponse:
    team = db.query(Team).filter(Team.id == payload.team_id).first()
    if not team:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Team not found")

    rounds = max(2, min(5, int(payload.rounds or 3)))
    task_id = str(uuid.uuid4())
    task = Task(
        id=task_id,
        team_id=payload.team_id,
        framework=payload.framework.value,
        task_description=payload.task_description,
        status="queued",
        current_phase="queued",
        final_output=None,
        metadata_json={
            "source": "debate_api",
            "mode": "debate",
            "rounds": rounds,
        },
    )
    db.add(task)
    db.flush()
    db.add(
        TaskTimelineEvent(
            task_id=task_id,
            agent_name="Supervisor",
            event_type="DEBATE_START",
            description=f"Debate queued for topic with {rounds} rounds.",
            metadata_json={"rounds": rounds, "framework": payload.framework.value},
        )
    )
    db.commit()
    db.refresh(task)
    asyncio.create_task(_execute_debate_async(task_id, payload.team_id, payload.task_description, rounds, payload.framework.value))
    return _to_task_response(task)


@router.get("/tasks")
async def list_tasks(db: Session = Depends(get_db)) -> list[TaskResponse]:
    rows = db.query(Task).order_by(Task.created_at.desc()).limit(100).all()
    results: list[TaskResponse] = []
    for row in rows:
        row = _mark_task_stalled_if_needed(db, row)
        results.append(_to_task_response(row))
    return results


@router.get("/tasks/{task_id}")
async def get_task(task_id: str, db: Session = Depends(get_db)) -> TaskResponse:
    task = db.query(Task).filter(Task.id == task_id).first()
    if not task:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found")
    task = _mark_task_stalled_if_needed(db, task)
    return _to_task_response(task)


@router.get("/tasks/{task_id}/messages")
async def get_task_messages(task_id: str, db: Session = Depends(get_db)) -> list[TaskMessageResponse]:
    if not db.query(Task.id).filter(Task.id == task_id).first():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found")
    rows = db.query(TaskMessage).filter(TaskMessage.task_id == task_id).order_by(TaskMessage.created_at.asc()).all()
    return [
        TaskMessageResponse(
            id=row.id,
            task_id=row.task_id,
            from_agent=row.from_agent,
            to_agent=row.to_agent,
            message_type=row.message_type,
            content=row.content,
            created_at=row.created_at.isoformat(),
        )
        for row in rows
    ]


@router.get("/tasks/{task_id}/timeline")
async def get_task_timeline(task_id: str, db: Session = Depends(get_db)) -> list[TaskTimelineResponse]:
    if not db.query(Task.id).filter(Task.id == task_id).first():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found")
    rows = db.query(TaskTimelineEvent).filter(TaskTimelineEvent.task_id == task_id).order_by(TaskTimelineEvent.created_at.asc()).all()
    return [
        TaskTimelineResponse(
            id=row.id,
            task_id=row.task_id,
            agent_name=row.agent_name,
            event_type=row.event_type,
            description=row.description,
            metadata=row.metadata_json or {},
            created_at=row.created_at.isoformat(),
        )
        for row in rows
    ]


@router.get("/tasks/{task_id}/stream")
async def stream_task(task_id: str, db: Session = Depends(get_db)) -> StreamingResponse:
    task = db.query(Task).filter(Task.id == task_id).first()
    if not task:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found")

    async def event_generator():
        session = SessionLocal()
        try:
            last_event_id = 0
            idle_ticks = 0
            last_status_snapshot: tuple[str, str] | None = None
            while idle_ticks < 120:  # ~2 minutes with 1s polling
                task_row = session.query(Task).filter(Task.id == task_id).first()
                if not task_row:
                    yield "event: error\ndata: {\"detail\":\"Task not found\"}\n\n"
                    break
                task_row = _mark_task_stalled_if_needed(session, task_row)

                status_snapshot = (task_row.status, task_row.current_phase)
                if status_snapshot != last_status_snapshot:
                    yield f"event: status\ndata: {json.dumps({'task_id': task_id, 'status': task_row.status, 'phase': task_row.current_phase})}\n\n"
                    last_status_snapshot = status_snapshot
                new_events = (
                    session.query(TaskTimelineEvent)
                    .filter(TaskTimelineEvent.task_id == task_id, TaskTimelineEvent.id > last_event_id)
                    .order_by(TaskTimelineEvent.id.asc())
                    .all()
                )

                if new_events:
                    for item in new_events:
                        data = {
                            "id": item.id,
                            "task_id": task_id,
                            "agent_name": item.agent_name,
                            "event_type": item.event_type,
                            "description": item.description,
                            "created_at": item.created_at.isoformat(),
                        }
                        yield f"event: timeline\ndata: {json.dumps(data)}\n\n"
                        last_event_id = item.id
                    idle_ticks = 0
                else:
                    idle_ticks += 1
                    yield "event: heartbeat\ndata: {\"ok\":true}\n\n"

                if task_row.status in {"completed", "failed"} and not new_events:
                    break
                await asyncio.sleep(2)
        finally:
            session.close()

    return StreamingResponse(event_generator(), media_type="text/event-stream")


@router.post("/tasks/{task_id}/compare")
async def compare_frameworks(task_id: str, payload: TaskCompareRequest, db: Session = Depends(get_db)) -> dict:
    task = db.query(Task).filter(Task.id == task_id).first()
    if not task:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Task not found")
    compare_task_description = payload.task_description or task.task_description
    return {
        "task_id": task_id,
        "comparison": {
            "langgraph": {"status": "queued", "task_description": compare_task_description},
            "crewai": {"status": "queued", "task_description": compare_task_description},
        },
        "note": "Comparison execution plumbing is ready; framework runs are implemented in next phase.",
    }

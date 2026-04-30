"""LangGraph supervisor-worker execution flow with quality gates."""

from __future__ import annotations

import time
import re
import operator
from typing import Any, Generator, TypedDict
from typing_extensions import Annotated

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_google_genai import ChatGoogleGenerativeAI
from langgraph.graph import END, START, StateGraph

from app.config import settings
from app.services.langgraph.worker_agents import build_agent_profile, get_tool_context, produce_worker_output
from app.services.performance_tracker import build_performance_entry


QUALITY_THRESHOLD = 0.7
MAX_REVISIONS = 2
DEFAULT_MODEL_FALLBACKS = ["gemini-flash-latest"]
LLM_PROVIDER_TIMEOUT_SECONDS = 12
LLM_OUTER_ATTEMPTS = 1
LLM_RETRY_BACKOFF_SECONDS = 0.8
LLM_MAX_TOTAL_SECONDS = 18


def _clean_output_text(text: str) -> str:
    if not text:
        return ""
    lines = text.splitlines()
    filtered: list[str] = []
    for line in lines:
        s = line.strip()
        if not s:
            filtered.append("")
            continue
        lower = s.lower()
        if "completed subtask:" in lower:
            continue
        if lower.startswith("revision round:"):
            continue
        filtered.append(line)
    cleaned = "\n".join(filtered).strip()
    while "\n\n\n" in cleaned:
        cleaned = cleaned.replace("\n\n\n", "\n\n")
    return cleaned


def _is_fallback_text(text: str) -> bool:
    lowered = (text or "").lower()
    return "fallback analysis" in lowered and "method: tool-context synthesis" in lowered


def _extract_fallback_reason(text: str) -> str:
    if not text:
        return "LLM unavailable."
    for line in text.splitlines():
        if "Method:" in line:
            return line.replace("- Method:", "").strip().rstrip(".")
    return "LLM unavailable."


def _strip_redundant_heading(text: str, section_title: str) -> str:
    if not text:
        return ""
    lines = text.splitlines()
    if not lines:
        return text
    normalized_title = section_title.strip().lower().rstrip(":")
    drop_idx = None
    for idx, raw in enumerate(lines[:3]):
        candidate = raw.strip().lstrip("#").strip().lower()
        candidate = candidate.rstrip(":")
        if candidate == normalized_title or candidate.startswith(f"{normalized_title}:"):
            drop_idx = idx
            break
    if drop_idx is None:
        return text
    trimmed = lines[:drop_idx] + lines[drop_idx + 1 :]
    return "\n".join(trimmed).strip()


def _first_output_by_role(completed_steps: list[dict], role: str) -> str:
    wanted = role.strip().lower()
    for item in completed_steps:
        current = (item.get("agent_role") or "").strip().lower()
        if current == wanted:
            return _clean_output_text(item.get("output", ""))
    return ""


def _latest_output_by_role(completed_steps: list[dict], role: str) -> str:
    wanted = role.strip().lower()
    for item in reversed(completed_steps):
        current = (item.get("agent_role") or "").strip().lower()
        if current == wanted:
            return _clean_output_text(item.get("output", ""))
    return ""


def _requested_points_count(task_description: str) -> int | None:
    if not task_description:
        return None
    text = task_description.lower()
    word_to_num = {
        "one": 1,
        "two": 2,
        "three": 3,
        "four": 4,
        "five": 5,
        "six": 6,
        "seven": 7,
        "eight": 8,
        "nine": 9,
        "ten": 10,
    }
    m_digit = re.search(r"\b(\d+)\s+(?:point|points|bullet|bullets)\b", text)
    if m_digit:
        return max(1, min(10, int(m_digit.group(1))))
    m_word = re.search(r"\b(one|two|three|four|five|six|seven|eight|nine|ten)\s+(?:point|points|bullet|bullets)\b", text)
    if m_word:
        return word_to_num.get(m_word.group(1))
    return None


def _limit_points(text: str, limit: int | None) -> str:
    if not text or not limit:
        return text
    lines = text.splitlines()
    out: list[str] = []
    kept = 0
    collecting = False
    for line in lines:
        marker = line.strip()
        is_point = bool(re.match(r"^(\d+[\.\)]\s+|[-*]\s+)", marker))
        if is_point:
            if kept >= limit:
                collecting = False
                continue
            kept += 1
            collecting = True
            out.append(line)
            continue
        if collecting:
            out.append(line)
        elif kept < limit:
            out.append(line)
    if kept == 0:
        # If no bullet/numbering exists, keep as-is (avoid destructive truncation).
        return text
    return "\n".join(out).strip()


def _build_structured_final_output(completed_steps: list[dict], task_description: str) -> str:
    requested_points = _requested_points_count(task_description)
    raw_research = _first_output_by_role(completed_steps, "researcher")
    raw_draft = _first_output_by_role(completed_steps, "writer")
    raw_reviewer = _latest_output_by_role(completed_steps, "reviewer")

    fallback_reasons: list[str] = []
    for block in (raw_research, raw_draft, raw_reviewer):
        if _is_fallback_text(block):
            fallback_reasons.append(_extract_fallback_reason(block))

    research = _strip_redundant_heading(raw_research, "Research Findings")
    research = _limit_points(research, requested_points)
    draft = _strip_redundant_heading(raw_draft, "Draft")
    reviewer_text = raw_reviewer
    review_notes = ""
    revised_output = reviewer_text
    if reviewer_text and "revised" in reviewer_text.lower() and "review" in reviewer_text.lower():
        splitter = "\n\n"
        parts = reviewer_text.split(splitter, 1)
        if len(parts) == 2:
            review_notes = parts[0].strip()
            revised_output = parts[1].strip()
    review_notes = _strip_redundant_heading(review_notes, "Review Notes")
    revised_output = _strip_redundant_heading(revised_output, "Final Revised Output")
    if _is_fallback_text(research):
        research = ""
    if _is_fallback_text(draft):
        draft = ""
    if _is_fallback_text(review_notes):
        review_notes = ""
    if _is_fallback_text(revised_output):
        revised_output = ""

    sections: list[str] = []
    if research:
        sections.append(f"## Research Findings\n{research}")
    if draft:
        sections.append(f"## Draft\n{draft}")
    if review_notes:
        sections.append(f"## Review Notes\n{review_notes}")
    if revised_output:
        sections.append(f"## Final Revised Output\n{revised_output}")

    if sections:
        if fallback_reasons:
            unique_reasons = []
            for reason in fallback_reasons:
                if reason and reason not in unique_reasons:
                    unique_reasons.append(reason)
            notice = "Fallback notice: " + " | ".join(unique_reasons)
            return f"{notice}\n\n" + "\n\n".join(sections).strip()
        return "\n\n".join(sections).strip()

    # Fallback for teams without classic roles.
    generic_blocks = []
    for item in completed_steps:
        generic_blocks.append(
            f"## {item['agent_name']} ({item['agent_role']})\n{_clean_output_text(item['output'])}"
        )
    if fallback_reasons:
        unique_reasons = []
        for reason in fallback_reasons:
            if reason and reason not in unique_reasons:
                unique_reasons.append(reason)
        notice = "Fallback notice: " + " | ".join(unique_reasons)
        return f"{notice}\n\n" + "\n\n".join(generic_blocks).strip()
    return "\n\n".join(generic_blocks).strip()


def _role_instruction(agent_role: str, step_number: int, task_description: str) -> str:
    role = (agent_role or "").strip().lower()
    requested_points = _requested_points_count(task_description)
    points_clause = (
        f"Return exactly {requested_points} point(s) when relevant to the user request. "
        if requested_points
        else ""
    )
    if role == "researcher":
        return (
            f"Step {step_number}: Research the task and produce factual findings only for: {task_description}. "
            f"{points_clause}"
            "Include concrete facts/statistics with sources or source hints. "
            "Do not write the final article outline."
        )
    if role == "writer":
        return (
            f"Step {step_number}: Create the deliverable draft for: {task_description}. "
            "Use prior research outputs as primary input. "
            "Focus on structure, clarity, and audience fit."
        )
    if role == "reviewer":
        return (
            f"Step {step_number}: Review and improve prior draft for: {task_description}. "
            "Provide review notes with strengths, issues, and precise fixes. "
            "Also provide a revised final version after applying your notes."
        )
    return f"Step {step_number}: Complete your role-specific contribution for: {task_description}."


def _profile_instruction(agent_profile: dict, step_number: int, task_description: str) -> str:
    base = _role_instruction(agent_profile.get("role", ""), step_number, task_description)
    approach = agent_profile.get("approach", "")
    contract = agent_profile.get("output_contract", "")
    expertise = agent_profile.get("expertise_domain", "general")
    return (
        f"{base}\n"
        f"Role specialization: {agent_profile.get('role', 'Specialist')} ({expertise}).\n"
        f"Approach: {approach}\n"
        f"Output contract: {contract}"
    ).strip()


def _build_handoff_context(completed_steps: list[dict]) -> str:
    if not completed_steps:
        return "No prior agent outputs yet."
    chunks: list[str] = []
    for item in completed_steps[-3:]:
        chunks.append(
            f"From {item['agent_name']} ({item['agent_role']}):\n"
            f"{item['output'][:1200]}"
        )
    return "\n\n---\n\n".join(chunks)


def _build_plan(task_description: str, team_agents: list[dict]) -> list[dict]:
    plan = []
    for idx, agent in enumerate(team_agents):
        agent_profile = build_agent_profile(agent)
        plan.append(
            {
                "step": idx + 1,
                "agent_id": agent["id"],
                "agent_name": agent["name"],
                "agent_role": agent["role"],
                "agent_profile": agent_profile,
                "instruction": _profile_instruction(agent_profile, idx + 1, task_description),
            }
        )
    return plan


def _build_llm(model_name: str):
    return ChatGoogleGenerativeAI(
        model=model_name,
        google_api_key=settings.google_api_key,
        temperature=0.2,
        timeout=LLM_PROVIDER_TIMEOUT_SECONDS,
        max_retries=0,
    )


def _model_candidates() -> list[str]:
    ordered = [settings.gemini_model, *DEFAULT_MODEL_FALLBACKS]
    deduped: list[str] = []
    for model_name in ordered:
        if model_name and model_name not in deduped:
            deduped.append(model_name)
    return deduped


def _invoke_agent_llm(
    *,
    agent_name: str,
    agent_role: str,
    task_description: str,
    instruction: str,
    tool_context: str,
    handoff_context: str,
    agent_profile: dict,
    revision_round: int,
) -> str:
    if not settings.google_api_key:
        return (
            f"{agent_name} fallback output.\n"
            f"Role: {agent_role}\nTask: {task_description}\nInstruction: {instruction}\n"
            "No GOOGLE_API_KEY configured, so tool-only reasoning was used."
        )
    messages = [
        SystemMessage(
            content=(
                f"You are {agent_name}, a specialized {agent_role} agent in a multi-agent system.\n"
                f"Communication style: {agent_profile.get('communication_style', 'professional')}.\n"
                f"Expertise domain: {agent_profile.get('expertise_domain', 'general')}.\n"
                f"Role approach: {agent_profile.get('approach', '')}\n"
                f"Output contract: {agent_profile.get('output_contract', '')}\n"
                f"Custom system prompt from user:\n{agent_profile.get('system_prompt', '')}\n"
                "Always produce role-faithful, concrete output."
            )
        ),
        HumanMessage(
            content=(
                f"Task description:\n{task_description}\n\n"
                f"Subtask instruction:\n{instruction}\n\n"
                f"Prior agent outputs (for handoff context):\n{handoff_context}\n\n"
                f"Tool context:\n{tool_context}\n\n"
                f"Revision round: {revision_round}. Improve quality if this is a revision."
            )
        ),
    ]

    last_error = None
    started_at = time.perf_counter()
    for attempt in range(LLM_OUTER_ATTEMPTS):
        if (time.perf_counter() - started_at) >= LLM_MAX_TOTAL_SECONDS:
            last_error = RuntimeError("LLM call budget exceeded")
            break
        for model_name in _model_candidates():
            if (time.perf_counter() - started_at) >= LLM_MAX_TOTAL_SECONDS:
                last_error = RuntimeError("LLM call budget exceeded")
                break
            try:
                llm = _build_llm(model_name)
                response = llm.invoke(messages)
                if hasattr(response, "content"):
                    raw_content = response.content
                    if isinstance(raw_content, str):
                        content = raw_content.strip()
                    elif isinstance(raw_content, list):
                        text_parts = []
                        for item in raw_content:
                            if isinstance(item, dict) and item.get("type") == "text":
                                text_parts.append(str(item.get("text", "")))
                            else:
                                text_parts.append(str(item))
                        content = "\n".join(part.strip() for part in text_parts if part).strip()
                    else:
                        content = str(raw_content).strip()
                else:
                    content = str(response).strip()
                if content:
                    return content
            except Exception as exc:
                last_error = exc
                continue
        if attempt < LLM_OUTER_ATTEMPTS - 1:
            # Retry whole model cycle for transient provider overload/timeouts.
            time.sleep(LLM_RETRY_BACKOFF_SECONDS * (attempt + 1))

    error_text = str(last_error or "")
    if "RESOURCE_EXHAUSTED" in error_text or "quota" in error_text.lower():
        reason = "Gemini quota limit reached for this project/key."
    elif "UNAVAILABLE" in error_text or "DEADLINE_EXCEEDED" in error_text:
        reason = "Gemini service is temporarily overloaded or timed out."
    else:
        reason = "LLM unavailable for current key/project."

    return (
        f"{agent_name} fallback analysis:\n"
        f"- Role: {agent_role}\n"
        f"- Task focus: {instruction}\n"
        f"- Method: tool-context synthesis ({reason}).\n"
        "- Draft output prepared with available tool evidence."
    )


class WorkflowState(TypedDict):
    task_description: str
    plan: list[dict]
    step_index: int
    current_step: dict | None
    current_result: dict | None
    current_revisions: int
    completed_steps: list[dict]
    metrics: list[dict]
    next_action: str
    final_output: str
    performance: list[dict]
    emitted_chunks: Annotated[list[dict], operator.add]


def _pick_reassignment_step(plan: list[dict], current_step: dict, completed_steps: list[dict]) -> dict | None:
    completed_names = {item["agent_name"] for item in completed_steps}
    current_name = current_step.get("agent_name", "")
    current_profile = (current_step.get("agent_profile") or {}).get("profile_id", "")
    for step in plan:
        if step["agent_name"] == current_name or step["agent_name"] in completed_names:
            continue
        profile_id = (step.get("agent_profile") or {}).get("profile_id", "")
        if current_profile and current_profile == profile_id:
            return step
    for step in plan:
        if step["agent_name"] != current_name and step["agent_name"] not in completed_names:
            return step
    return None


def _node_supervisor_decide(state: WorkflowState) -> dict:
    if state["step_index"] >= len(state["plan"]):
        return {"next_action": "synthesize", "current_step": None}
    step = state["plan"][state["step_index"]]
    return {"current_step": step, "current_revisions": 0, "next_action": "delegate"}


def _node_delegate(state: WorkflowState) -> dict:
    step = state["current_step"]
    if not step:
        return {}
    return {
        "emitted_chunks": [
            {
                "timeline_event": {
                    "agent_name": "Supervisor",
                    "event_type": "DELEGATION",
                    "description": f"Delegated subtask {step['step']} to {step['agent_name']}.",
                    "metadata": {"step": step["step"], "agent_id": step["agent_id"]},
                },
                "message": {
                    "from_agent": "Supervisor",
                    "to_agent": step["agent_name"],
                    "message_type": "DELEGATION",
                    "content": step["instruction"],
                },
            }
        ]
    }


def _node_execute(state: WorkflowState) -> dict:
    step = state["current_step"]
    if not step:
        return {}
    profile = step.get("agent_profile", {})
    tool_context = get_tool_context(
        step["agent_role"],
        state["task_description"],
        agent_tools=[*(profile.get("declared_tools", []) or []), *(profile.get("preferred_tools", []) or [])],
        expertise_domain=profile.get("expertise_domain", ""),
    )
    handoff_context = _build_handoff_context(state["completed_steps"])
    llm_output = _invoke_agent_llm(
        agent_name=step["agent_name"],
        agent_role=step["agent_role"],
        task_description=state["task_description"],
        instruction=step["instruction"],
        tool_context=tool_context,
        handoff_context=handoff_context,
        agent_profile=profile,
        revision_round=state["current_revisions"],
    )
    result = produce_worker_output(
        agent_name=step["agent_name"],
        agent_role=step["agent_role"],
        task_description=state["task_description"],
        instruction=step["instruction"],
        revision_round=state["current_revisions"],
        llm_output=llm_output,
    )
    return {"current_result": result}


def _node_quality_gate(state: WorkflowState) -> dict:
    step = state["current_step"]
    result = state["current_result"] or {}
    if not step:
        return {"next_action": "advance"}

    quality = float(result.get("quality") or 0.0)
    if quality >= QUALITY_THRESHOLD:
        output_text = str(result.get("output") or "")
        return {
            "completed_steps": [
                {
                    "agent_name": step["agent_name"],
                    "agent_role": step["agent_role"],
                    "output": output_text,
                }
            ],
            "metrics": [
                {
                    "agent_id": step["agent_id"],
                    "quality_score": quality,
                    "response_time_ms": int(result.get("response_time_ms") or 0),
                    "token_usage": int(result.get("token_usage") or 0),
                    "revision_count": state["current_revisions"],
                    "output_length": len(output_text),
                }
            ],
            "step_index": state["step_index"] + 1,
            "next_action": "advance",
            "emitted_chunks": [
                {
                    "timeline_event": {
                        "agent_name": step["agent_name"],
                        "event_type": "SUBMISSION",
                        "description": f"{step['agent_name']} submitted output for step {step['step']}.",
                        "metadata": {"step": step["step"], "quality": quality},
                    },
                    "message": {
                        "from_agent": step["agent_name"],
                        "to_agent": "Supervisor",
                        "message_type": "SUBMISSION",
                        "content": output_text,
                    },
                }
            ],
        }

    if state["current_revisions"] < MAX_REVISIONS:
        return {
            "current_revisions": state["current_revisions"] + 1,
            "next_action": "revise",
            "emitted_chunks": [
                {
                    "timeline_event": {
                        "agent_name": "Supervisor",
                        "event_type": "REVISION_REQUEST",
                        "description": f"Requested revision from {step['agent_name']} (quality={quality:.2f}).",
                        "metadata": {"step": step["step"], "quality": quality},
                    },
                    "message": {
                        "from_agent": "Supervisor",
                        "to_agent": step["agent_name"],
                        "message_type": "REVISION_REQUEST",
                        "content": "Improve factual precision, structure, and relevance.",
                    },
                }
            ],
        }

    reassigned = _pick_reassignment_step(state["plan"], step, state["completed_steps"])
    if reassigned:
        reassigned_step = {
            **reassigned,
            "step": step["step"],
            "instruction": f"{step['instruction']}\n(You are reassigned as backup for this subtask.)",
        }
        return {
            "current_step": reassigned_step,
            "current_revisions": 0,
            "next_action": "reassign",
            "emitted_chunks": [
                {
                    "timeline_event": {
                        "agent_name": "Supervisor",
                        "event_type": "REASSIGNMENT",
                        "description": f"Reassigned step {step['step']} from {step['agent_name']} to {reassigned['agent_name']}.",
                        "metadata": {"step": step["step"], "from": step["agent_name"], "to": reassigned["agent_name"]},
                    },
                    "message": {
                        "from_agent": "Supervisor",
                        "to_agent": reassigned["agent_name"],
                        "message_type": "DELEGATION",
                        "content": reassigned_step["instruction"],
                    },
                }
            ],
        }

    output_text = str(result.get("output") or "")
    return {
        "completed_steps": [
            {
                "agent_name": step["agent_name"],
                "agent_role": step["agent_role"],
                "output": output_text,
            }
        ],
        "metrics": [
            {
                "agent_id": step["agent_id"],
                "quality_score": quality,
                "response_time_ms": int(result.get("response_time_ms") or 0),
                "token_usage": int(result.get("token_usage") or 0),
                "revision_count": state["current_revisions"],
                "output_length": len(output_text),
            }
        ],
        "step_index": state["step_index"] + 1,
        "next_action": "advance",
    }


def _node_synthesize(state: WorkflowState) -> dict:
    final_output = _build_structured_final_output(state["completed_steps"], state["task_description"])
    output_sections = final_output.count("\n## ") + (1 if final_output.startswith("## ") else 0)
    total_chars = sum(item["output_length"] for item in state["metrics"])
    performance = []
    for item in state["metrics"]:
        perf = build_performance_entry(
            quality_score=item["quality_score"],
            response_time_ms=item["response_time_ms"],
            revision_count=item["revision_count"],
            contribution_chars=item["output_length"],
            total_chars=total_chars,
            token_usage=item["token_usage"],
            error_count=0,
        )
        performance.append({"agent_id": item["agent_id"], **perf})
    return {
        "final_output": final_output,
        "performance": performance,
        "emitted_chunks": [
            {
                "timeline_event": {
                    "agent_name": "Supervisor",
                    "event_type": "SYNTHESIS",
                    "description": "Supervisor synthesized final deliverable.",
                    "metadata": {"output_sections": output_sections},
                },
            }
        ],
    }


def _route_after_supervisor(state: WorkflowState) -> str:
    return "synthesize" if state.get("next_action") == "synthesize" else "delegate"


def _route_after_quality_gate(state: WorkflowState) -> str:
    action = state.get("next_action")
    if action in {"revise", "reassign"}:
        return "execute"
    return "supervisor_decide"


def run_supervisor_workflow_stream(task_description: str, team_agents: list[dict]) -> Generator[dict, None, None]:
    plan = _build_plan(task_description, team_agents)
    workflow = StateGraph(WorkflowState)
    workflow.add_node("supervisor_decide", _node_supervisor_decide)
    workflow.add_node("delegate", _node_delegate)
    workflow.add_node("execute", _node_execute)
    workflow.add_node("quality_gate", _node_quality_gate)
    workflow.add_node("synthesize", _node_synthesize)
    workflow.add_edge(START, "supervisor_decide")
    workflow.add_conditional_edges(
        "supervisor_decide",
        _route_after_supervisor,
        {"delegate": "delegate", "synthesize": "synthesize"},
    )
    workflow.add_edge("delegate", "execute")
    workflow.add_edge("execute", "quality_gate")
    workflow.add_conditional_edges(
        "quality_gate",
        _route_after_quality_gate,
        {"execute": "execute", "supervisor_decide": "supervisor_decide"},
    )
    workflow.add_edge("synthesize", END)
    graph = workflow.compile()

    initial_state: WorkflowState = {
        "task_description": task_description,
        "plan": plan,
        "step_index": 0,
        "current_step": None,
        "current_result": None,
        "current_revisions": 0,
        "completed_steps": [],
        "metrics": [],
        "next_action": "delegate",
        "final_output": "",
        "performance": [],
        "emitted_chunks": [],
    }

    latest_state = initial_state
    for step_update in graph.stream(initial_state):
        for _node_name, update in step_update.items():
            if isinstance(update, dict):
                latest_state = {**latest_state, **update}
                for chunk in update.get("emitted_chunks", []) or []:
                    yield chunk

    yield {
        "done": True,
        "final_output": latest_state.get("final_output", ""),
        "performance": latest_state.get("performance", []),
    }

"""LangGraph-style debate runtime stream."""

from __future__ import annotations

from typing import Generator

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_google_genai import ChatGoogleGenerativeAI

from app.config import settings

LLM_TIMEOUT_SECONDS = 12


def _build_llm() -> ChatGoogleGenerativeAI | None:
    if not settings.google_api_key:
        return None
    return ChatGoogleGenerativeAI(
        model=settings.gemini_model,
        google_api_key=settings.google_api_key,
        temperature=0.2,
        timeout=LLM_TIMEOUT_SECONDS,
        max_retries=0,
    )


def _llm_or_fallback(system_prompt: str, user_prompt: str, fallback: str) -> str:
    llm = _build_llm()
    if not llm:
        return fallback
    try:
        response = llm.invoke([SystemMessage(content=system_prompt), HumanMessage(content=user_prompt)])
        content = response.content if hasattr(response, "content") else response
        if isinstance(content, list):
            parts = []
            for item in content:
                if isinstance(item, dict) and item.get("type") == "text":
                    parts.append(str(item.get("text", "")))
                else:
                    parts.append(str(item))
            return "\n".join(part.strip() for part in parts if part).strip() or fallback
        return str(content).strip() or fallback
    except Exception:
        return fallback


def run_debate_workflow_stream(
    topic: str,
    pro_agent_name: str,
    con_agent_name: str,
    judge_agent_name: str,
    rounds: int = 3,
) -> Generator[dict, None, None]:
    rounds = max(2, min(5, rounds))
    transcript: list[dict[str, str | int]] = []

    for idx in range(rounds):
        round_no = idx + 1
        pro_context = "\n".join(
            f"{item['speaker']}: {item['argument']}" for item in transcript[-4:] if item["side"] in {"pro", "con"}
        )
        pro_argument = _llm_or_fallback(
            system_prompt=f"You are {pro_agent_name}, the Pro advocate in a structured debate.",
            user_prompt=(
                f"Topic: {topic}\nRound: {round_no}/{rounds}\n"
                f"Recent context:\n{pro_context or 'No prior points.'}\n"
                "Give one concise pro argument with evidence-based reasoning."
            ),
            fallback=f"Pro fallback argument (round {round_no}): emphasize benefits and practical upside.",
        )
        transcript.append({"round": round_no, "side": "pro", "speaker": pro_agent_name, "argument": pro_argument})
        yield {
            "timeline_event": {
                "agent_name": pro_agent_name,
                "event_type": "DEBATE_ROUND",
                "description": f"Round {round_no}: Pro argument submitted.",
                "metadata": {"round": round_no, "side": "pro"},
            },
            "message": {
                "from_agent": pro_agent_name,
                "to_agent": con_agent_name,
                "message_type": "ARGUMENT",
                "content": pro_argument,
            },
        }

        con_context = "\n".join(
            f"{item['speaker']}: {item['argument']}" for item in transcript[-4:] if item["side"] in {"pro", "con"}
        )
        con_argument = _llm_or_fallback(
            system_prompt=f"You are {con_agent_name}, the Con critic in a structured debate.",
            user_prompt=(
                f"Topic: {topic}\nRound: {round_no}/{rounds}\n"
                f"Recent context:\n{con_context}\n"
                "Respond directly to Pro's latest point and provide one concise counterargument."
            ),
            fallback=f"Con fallback argument (round {round_no}): highlight risks, limits, and trade-offs.",
        )
        transcript.append({"round": round_no, "side": "con", "speaker": con_agent_name, "argument": con_argument})
        yield {
            "timeline_event": {
                "agent_name": con_agent_name,
                "event_type": "DEBATE_ROUND",
                "description": f"Round {round_no}: Con argument submitted.",
                "metadata": {"round": round_no, "side": "con"},
            },
            "message": {
                "from_agent": con_agent_name,
                "to_agent": pro_agent_name,
                "message_type": "ARGUMENT",
                "content": con_argument,
            },
        }

    transcript_text = "\n".join(
        f"Round {item['round']} - {item['speaker']} ({item['side']}): {item['argument']}" for item in transcript
    )
    verdict = _llm_or_fallback(
        system_prompt=f"You are {judge_agent_name}, the neutral Judge for a debate.",
        user_prompt=(
            f"Topic: {topic}\n"
            f"Debate transcript:\n{transcript_text}\n\n"
            "Write a balanced verdict with: strongest pro point, strongest con point, and final recommendation."
        ),
        fallback="Judge fallback verdict: both sides made useful points; choose based on context and risk tolerance.",
    )
    yield {
        "timeline_event": {
            "agent_name": judge_agent_name,
            "event_type": "JUDGE_VERDICT",
            "description": "Judge synthesized the final verdict.",
            "metadata": {"rounds": rounds},
        },
        "message": {
            "from_agent": judge_agent_name,
            "to_agent": "All",
            "message_type": "VERDICT",
            "content": verdict,
        },
    }
    yield {
        "done": True,
        "final_output": verdict,
        "metadata": {
            "rounds": rounds,
            "transcript": transcript,
        },
    }

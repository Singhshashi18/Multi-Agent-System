# Multi-Agent Collaboration System

An early-stage, LangGraph-first multi-agent collaboration platform with a FastAPI backend and React frontend.

## Overview

This repository is building a structured system for creating and running teams of AI agents that can collaborate, debate, and compare outcomes on shared tasks.

The goal is to make multi-agent workflows easier to design, observe, and improve over time through clear orchestration, streaming execution, and performance visibility.

## Current Status

This project is currently in scaffold/early implementation phase.

- Initial project scaffold is in progress
- Backend direction: FastAPI + LangGraph services
- Frontend direction: React + TypeScript UI
- Core routes, team templates, and flow placeholders are being defined

## Planned Capabilities

- Agent and team schema management
- Supervisor graph with worker agent nodes
- Task execution with SSE streaming
- Debate graph for multi-agent reasoning
- Performance tracking and comparison workflows
- Team builder and collaboration views in the frontend
- Debate, result comparison, and dashboard views
- CrewAI integration (next phase)

## Tech Stack / Architecture

- **Orchestration:** LangGraph
- **Backend API:** FastAPI
- **Frontend:** React + TypeScript
- **Communication pattern:** API + streaming (SSE planned)

## Repository Structure

> Current branch snapshot is minimal; below is the intended scaffold structure.

- `backend/` — FastAPI + LangGraph services
- `frontend/` — React UI

## Getting Started

Because this repo is in early scaffold state, setup commands may evolve. Use the steps below as safe starter guidance.

1. Clone the repository.
2. Create backend and frontend environment configs as needed.
3. Install dependencies in each app directory.
4. Run backend and frontend dev servers separately.

### TODO: Confirm exact local commands

When scaffold files are finalized, update this section with exact commands, for example:

- Backend install/run commands
- Frontend install/run commands
- Environment variable setup

## Roadmap

Implementation order currently tracked:

1. Agent and team schemas
2. Supervisor graph and worker agent nodes
3. Task execution + SSE streaming
4. Debate graph
5. Performance tracking
6. Frontend team builder + collaboration view
7. Frontend debate + comparison + dashboard
8. CrewAI integration

## Demo / Screenshots

Demo assets are not available yet. Add UI screenshots or short workflow GIFs here once available.

## Contributing

Contributions are welcome as the scaffold matures.

1. Fork the repository
2. Create a feature branch
3. Make focused changes
4. Open a pull request with a clear summary

If contribution guidelines are added later, this section should link to them.

## License

No license file is currently included in this repository.

> TODO: Add a `LICENSE` file and update this section with the selected license.

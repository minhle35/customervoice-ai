# CustomerVoice AI

CustomerVoice AI is a SaaS analytics dashboard for marketing teams to analyze customer feedback
from Google Reviews, Reddit, and Facebook using AI and LLMs. The system ingests reviews, enriches
and embeds them, and serves insights and AI-assisted analytics through a modern dashboard.

## Goals
- Centralize review ingestion from multiple platforms
- Run ETL pipelines for cleaning, sentiment, topic extraction, and embeddings
- Provide semantic search and RAG-based AI assistant
- Maintain scalable, modular architecture for enterprise readiness

## Tech Stack
Frontend: Next.js (App Router), TypeScript, TailwindCSS, shadcn/ui, TanStack Query, Recharts, lucide-react
Backend: FastAPI, Pydantic, SQLAlchemy, Celery, Redis
Database: PostgreSQL + pgvector
AI: OpenAI API (embeddings + chat), RAG pipeline

## Project Structure
See `docs/architecture.md` for the high-level architecture and data flow.

## Development (planned)
- `docker-compose.yml` for local stack
- `Makefile` targets for common tasks
- `.env.example` for required environment variables


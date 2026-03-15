# System Design

Key components:
- FastAPI backend with clear API boundaries
- Celery workers for background ETL jobs
- PostgreSQL + pgvector for structured + semantic search
- Redis for queues and caching
- OpenAI for embeddings and RAG chat


# Architecture Overview

CustomerVoice AI is built with a modular, scalable architecture:

- Ingestion layer fetches reviews from Google, Reddit, and Facebook.
- ETL pipelines normalize, clean, and enrich review data.
- Embeddings are generated and stored in pgvector for semantic search.
- Backend APIs serve analytics, insights, and AI chat responses.
- Frontend dashboard consumes APIs for real-time insights.


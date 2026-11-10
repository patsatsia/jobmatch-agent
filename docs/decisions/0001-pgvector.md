
# 0001: Use pgvector inside Postgres for vector search

- Status: Accepted
- Date: 2026-11-10

## Context
We need to store job postings, their embeddings, and app data (LLM call logs, eval results).

## Decision
Use PostgreSQL with the pgvector extension instead of a separate vector database.

## Consequences
- One database to run, back up and migrate; vector search and SQL filters (remote, visa, date) in one query.
- Enough performance at this scale (thousands of jobs) with an HNSW index.
- If we ever needed hundreds of millions of vectors, a dedicated vector DB could be reconsidered.
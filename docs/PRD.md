# Product Requirements Document — The Lenny Growth Assistant

## 1. Product Overview

The Lenny Growth Assistant is a conversational application that helps product managers, founders, and growth professionals find actionable insights from Lenny's Podcast transcripts.

The application will answer knowledge-based questions, generate structured written content, and render Markdown or HTML/CSS artifacts directly in the product.

## 2. User and Problem

**Primary users:** Product managers, founders, and growth professionals.

**Job to be done:** Find relevant advice from Lenny's Podcast, understand its context and supporting evidence, and turn that knowledge into a useful output.

**Problem:** Manually searching long transcripts is time-consuming. AI-generated answers without verifiable sources risk misrepresenting a guest's advice.

## 3. Success Metrics

Initial targets, to be validated during implementation:

- Build a manually reviewed evaluation set of at least 20 questions.
- Target at least 80% retrieval of the expected evidence chunk in the top five results for answerable evaluation questions.
- Require every displayed citation to resolve to a real transcript source or stored chunk.
- Test explicit abstention for unsupported questions.
- Demonstrate a working local Ollama chat workflow.
- Verify persistence and isolation across chat sessions.

## 4. Assumptions

- The assignment-linked transcript archive is the primary knowledge source.
- The initial demonstration is a locally operated, single-user application.
- Cloud-model access may be rate-limited or temporarily unavailable.
- The source archive is obtained separately and is not committed into the application repository.
- Only verified source URLs and timestamps will be presented as citations.

## 5. Scope

### Included

- Transcript discovery, ingestion, chunking, and indexing.
- Retrieval and source-grounded conversational answers.
- Independent sessions and PostgreSQL persistence.
- Configurable local and cloud model providers.
- A dedicated Ship 30 for 30-style essay capability.
- Markdown and HTML/CSS artifact generation and rendering.
- Automated tests, operational documentation, and a reproducible local setup.

### Initially excluded

- User authentication and multi-tenant permissions.
- External web research embedded in conversational answers.
- Model fine-tuning.
- Advanced autonomous workflows unrelated to the required product tasks.

These exclusions can be reconsidered after the required workflow is working.

## 6. Risks and Trade-offs

- Incomplete metadata or inconsistent transcript structure.
- Retrieval errors and unsupported claims.
- Local model latency and cloud API limits.
- Incompatibility between some agent SDK tools and non-native model providers.
- Unsafe rendering of generated HTML.
- Difficulty reproducing the project on another machine.

## 7. Initial Implementation Plan

1. Bootstrap the repository and audit the transcript corpus.
2. Build PostgreSQL and pgvector ingestion.
3. Implement retrieval and grounding tests.
4. Build FastAPI endpoints and session persistence.
5. Integrate the local and cloud model paths.
6. Add the writing and artifact skills.
7. Complete the interface, automated tests, and operational handoff.
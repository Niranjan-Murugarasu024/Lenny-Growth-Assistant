# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

1. **Founders & Operators**: Startup executives and technical founders seeking battle-tested strategic frameworks, operational benchmarks, and product leadership mental models distilled directly from world-class operators.
2. **Product Managers & Growth Leaders**: PMs, VPs of Product, and Growth Directors seeking tactical blueprints (e.g., pricing strategy, cohort retention loops, activation funnels, 11-star experiences) with direct quotation provenance.
3. **Knowledge Workers & Essayists**: Professional writers and analysts drafting research-backed long-form essays, newsletter analyses, and strategic briefs who require immutable version snapshots, citation traceability, and distraction-free editorial polish.

## Product Purpose

The Lenny Growth Assistant is a full-stack conversational AI assistant grounded in *Lenny's Podcast*. Its primary mission is enabling founders, product managers, and growth leaders to ask strategic, tactical, and operational questions and receive rigorously grounded answers with verifiable podcast passage citations. As contextual secondary capabilities, it provides Ship 30 for 30 essay generation and an in-app Artifact Viewer with immutable versioning and strict quality evaluation.

## Product Tagline

"Ask product, growth and startup questions. Get answers grounded in Lenny's Podcast, with traceable sources and reusable artifacts."

## Positioning

Unlike generic AI chatbots that hallucinate quotes or summarize without provenance, The Lenny Growth Assistant grounds every conversational answer strictly in an indexed archive of 303 podcast episodes and 17,365 chunks from *Lenny's Podcast*. It enforces backend-authoritative citation validation, links to verified episode timestamps and YouTube deep links, and enables on-demand synthesis of reusable writing artifacts.

## Operating Context

- **Primary Workflow**: Users ask product and growth questions via an intuitive chat interface, receive source-grounded answers with verifiable audio timestamps, and explore related podcast evidence without leaving the conversation.
- **Secondary Workflow**: From any grounded answer, users can trigger contextual "Create Ship 30 for 30 essay" or "Create artifact" actions, review real-time queue states, edit drafts in a distraction-free Markdown editor with sanitized HTML preview, and commit revisions as immutable version snapshots.
- **Environments**: Runs as a self-contained local stack or multi-container Docker Compose deployment (PostgreSQL 17 with pgvector, Redis 7, FastAPI backend, dedicated writing worker, Node.js Pi agent service, React 19/Vite/Nginx frontend).

## Capabilities and Constraints

- **Capabilities**:
  - Full-text and vector hybrid retrieval via Reciprocal Rank Fusion (RRF).
  - Grounded conversational chat via direct RAG and autonomous Pi Coding Agent service with controlled retrieval tools.
  - Asynchronous essay generation with durable Redis coordination, PostgreSQL authoritative state, and automatic crash recovery.
  - Deterministic essay quality evaluation (word count target bounds ±10%, minimum 2 section headings, central thesis identification, unverified citation rejection).
  - Version history with immutable revision snapshots, manual editing, and server-side sanitized HTML preview (`nh3`).
- **Constraints**:
  - Zero tolerance for leaked secrets: database passwords and internal service tokens must never appear in frontend bundles or command logs.
  - No claims without transcript grounding: citation validation is strictly backend-authoritative.
  - At-least-once durable execution with idempotency deduplication: duplicate submissions must never produce duplicate artifacts.

## Brand Commitments

- **Voice & Tone**: Calm, editorial, intellectually rigorous, and respectful of source material.
- **Visual Identity**: Serene editorial design with high-contrast typography (Newsreader serif headings, Inter interface, JetBrains Mono code/citations), generous 68ch reading measure, and restrained indigo accents.
- **Name**: The Lenny Growth Assistant.

## Evidence on Hand

- **Corpus**: 303 complete podcast episode transcripts and 17,365 embedded chunks with 768-dimensional vector embeddings (`nomic-embed-text:v1.5`).
- **Citation Provenance**: Verbatim transcript quotes, speaker attribution, episode titles, audio start timestamps, and cosine distances stored in PostgreSQL.
- **Absence**: Does not include unverified third-party web content, outside blogs, or fabricated interview dialogue.

## Product Principles

1. **Evidence Traceability Over Fluency**: Every substantive claim must resolve to an authentic podcast passage. Ungrounded fluency is treated as a defect.
2. **Calm Editorial Atmosphere**: The workspace recedes so the document leads. Reading comfort, generous line height, and distraction-free measure outrank decorative chrome.
3. **Objective Quality Transparency**: Evaluation scores and word count bounds are displayed plainly without euphemism or hidden score tampering.
4. **Immutable Draft Provenance**: Every version is permanently preserved. Authors can explore revisions fearlessly without destructive overwrite.
5. **Absolute Security & Containment**: Rendered HTML is strictly sanitized against code execution; internal tokens and credentials remain strictly contained.

## Accessibility & Inclusion

- Adherence to WCAG 2.1 AA standards for contrast ratios (minimum 4.5:1 for body text, 3:1 for large headers).
- Unambiguous 2px focus rings (`outline: 2px solid var(--primary); outline-offset: 2px`) on all interactive buttons, inputs, tabs, and drawer controls.
- Responsive design supporting viewports from mobile (375px) through high-resolution desktop displays with full touch and keyboard navigation.

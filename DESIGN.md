# Design System & UI Specifications — The Lenny Growth Assistant

**Document:** `design.md`  
**Application:** The Lenny Growth Assistant  
**Design Philosophy:** Editorial-grade typography, high-clarity information architecture, seamless split-pane writing workspace, responsive across viewports from mobile to ultra-wide desktop.

---

## 1. Information Architecture & Spatial Model

The Lenny Growth Assistant integrates two primary modes of intellectual work into a cohesive layout:
1. **Conversational Exploration:** Fast, multi-turn Q&A grounded in transcript evidence.
2. **Artifact Writing & Refinement:** Focused drafting, reading, and editing of publication-ready essays.

### 1.1 Viewport Partitioning & Layout States
```
+-----------------------------------------------------------------------------------+
| Top Navigation Bar: Brand | Orchestrator (RAG/Pi) | Model Selector | Workspace Tab|
+-----------------------------------------------------------------------------------+
| Sidebar         | Left Pane: Chat Stream            | Right Pane: Artifact Viewer |
| - Sessions List | - Message history                 | - Title & Monotonic Version |
| - Essay Library | - Citations pills & drawers       | - Diagnostic Quality Banner |
| - Settings      | - Chat Composer input             | - View Mode (Split/Ed/HTML) |
|                 |                                   | - Markdown / HTML Preview   |
|                 |                                   | - Async AI Revision Bar     |
+-----------------------------------------------------------------------------------+
```

### 1.2 Viewport Modes & Responsiveness
- **Desktop Ultra-Wide & Standard (>= 1024px):**
  - Side-by-side split container (`.chat-split-container`) with chat pane and artifact pane.
  - Independent scrolling containers: message list, editor, and preview scroll independently without page-level scrollbars.
  - Full-width writing expansion toggle (`Expand Workspace` / `Split View`) allowing the artifact pane to occupy the full content area for distraction-free editing.
- **Tablet & Mobile (< 768px):**
  - Stacked vertical layout: `.chat-split-container` automatically reflows to `flex-direction: column`.
  - Pane min-height and width adapt to 100%, eliminating horizontal clipping.
  - Mobile header toggles between Chat and Workspace views.

---

## 2. Color Palette & Visual Tokens

The aesthetic draws on premium editorial publishing standards: crisp backgrounds, legible warm-toned serif headings, neutral dark text, and subtle status indicators.

| Token | Hex Value | Semantic Usage |
| :--- | :--- | :--- |
| `primary` | `#4f46e5` | Primary CTA buttons, active tab indicators, focus rings |
| `primary-hover` | `#4338ca` | Hover state for primary interactive elements |
| `primary-light` | `#eef2ff` | Citation chips, subtle pill backgrounds, selected highlights |
| `bg-page` | `#f8fafc` | Global background canvas |
| `bg-surface` | `#ffffff` | Panel surfaces, dialog modals, editor background |
| `bg-subtle` | `#f1f5f9` | Assistant chat bubble background, table headers |
| `bg-muted` | `#e2e8f0` | Dividers, secondary button borders, disabled states |
| `text-main` | `#0f172a` | High-contrast body typography, titles, primary text |
| `text-secondary` | `#475569` | Subheadings, author metadata, timestamp labels |
| `text-muted` | `#64748b` | Placeholders, helper hints, inactive tabs |
| `status-success` | `#065f46` / `#ecfdf5` | Passed quality checks, completed jobs |
| `status-warning` | `#b45309` / `#fef3c7` | Out-of-range word counts, quality advisories |
| `status-error` | `#991b1b` / `#fef2f2` | Failed worker jobs, missing citations, error banners |

---

## 3. Typography Hierarchy

- **Display & Artifact Titles:** `Newsreader`, `Georgia`, serif (2.1rem / 700 / line-height 1.2 / letter-spacing -0.025em). Editorial, authoritative, and book-like.
- **Interface Headings:** `Inter`, `-apple-system`, sans-serif (1.45rem / 700 / line-height 1.3 / letter-spacing -0.02em). Clean, geometric, and modern.
- **Body & Chat Text:** `Inter`, `-apple-system`, sans-serif (1.05rem / 400 / line-height 1.75). Highly legible reading experience with generous line spacing.
- **Code & Citations:** `JetBrains Mono`, `Menlo`, monospace (0.88rem / 400 / line-height 1.5). For source chunk IDs, timestamps, and markdown code blocks.

---

## 4. Key Interactive Components

### 4.1 Artifact Viewer & Workspace
- **View Modes:**
  - `Split`: Side-by-side editing pane and rendered live preview.
  - `Editor`: Focused markdown editor with syntax assistance.
  - `HTML Preview`: Sandboxed iframe preview styled with publication CSS.
- **Diagnostics Quality Banner:**
  - If a draft does not pass strict quality criteria (e.g. word count out of range or ungrounded claims), a high-visibility diagnostic banner renders at the top of the artifact displaying:
    - Target word count range vs actual body word count.
    - Specific missing criteria (e.g. *Clear central thesis statement*).
    - Citation count and traceability status.
    - Status badge: `Needs revision` (not hidden, fully editable).
- **Asynchronous Revision Bar:**
  - Sticky bottom input allowing users to request AI revisions without blocking chat.
  - Live stage indicator during processing (`Submitting...`, `Executing revision...`, `Completed`).

### 4.2 Sources & Citations Drawer
- Inline citation chips (`[Source 1: Brian Chesky]`) in chat answers and essay references.
- Clicking opens a slide-over drawer showing:
  - Episode title, guest, release date, and YouTube thumbnail.
  - Direct timestamp link to audio/video.
  - Exact transcribed quote and cosine similarity distance.

### 4.3 Model & Orchestrator Switcher
- Persistent top-bar controls for:
  - **Orchestrator:** Direct RAG (sub-second) vs Pi Coding Agent (multi-turn reasoning).
  - **Model:** Local Ollama (`qwen2.5:1.5b`) vs Cloud NVIDIA NIM (`openai/gpt-oss-20b`).
  - Authoritative backend synchronization: updates database settings table immediately.

---

## 5. Accessibility & Interaction Polish
- **Color Contrast:** All text tokens meet WCAG 2.1 AA standards (minimum 4.5:1 contrast against surface backgrounds).
- **Focus Management:** Visible `2px solid #4f46e5` focus rings on all inputs, select menus, and buttons.
- **No Frozen Spinners:** Background writing operations report structured stages rather than indefinite blank spinners.
- **Keyboard Navigation:** Escape closes drawers and modal dialogs; Enter submits revision inputs.

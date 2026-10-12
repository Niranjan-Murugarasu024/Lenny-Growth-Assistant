import React from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { ChatView } from '../components/ChatView';
import { Sidebar } from '../components/Sidebar';
import { SourcesSection } from '../components/SourcesSection';
import { EssayDialog } from '../components/EssayDialog';
import { Header } from '../components/Header';
import { App } from '../App';
import { apiClient } from '../api/client';
import type { ChatMessage, ChatSession, SourceReference } from '../api/types';

const mockSources: SourceReference[] = [
  {
    citation_index: 1,
    is_cited: true,
    chunk_id: 14304,
    chunk_index: 1,
    source_path: 'episodes/rahul-vohra/transcript.md',
    guest: 'Rahul Vohra',
    title: "Superhuman's secret to success | Rahul Vohra",
    timestamp: '00:02:15',
    start_time_seconds: 135,
    cosine_distance: 0.223,
    excerpt: 'We asked users how they would feel if they could no longer use Superhuman.',
    youtube_video_id: 'l-T8sNRcWQk',
    youtube_url: 'https://www.youtube.com/watch?v=l-T8sNRcWQk&t=135s',
  },
];

const mockMessages: ChatMessage[] = [
  {
    id: 1,
    session_id: 'sess-123',
    role: 'user',
    content: 'What is Rahul Vohra product market fit framework?',
    created_at: '2026-10-12T00:00:00Z',
  },
  {
    id: 2,
    session_id: 'sess-123',
    role: 'assistant',
    content: 'Rahul Vohra measured PMF with the 40% threshold survey asking how users would feel without Superhuman [Source 1].',
    provider: 'ollama',
    model: 'qwen3.5:9b',
    sources: mockSources,
    created_at: '2026-10-12T00:00:10Z',
  },
];

const mockSessions: ChatSession[] = [
  {
    id: 'sess-123',
    title: 'Product Market Fit Framework',
    created_at: '2026-10-12T00:00:00Z',
    updated_at: '2026-10-12T00:01:00Z',
  },
  {
    id: 'sess-456',
    title: 'Growth team structure',
    created_at: '2026-10-12T00:00:00Z',
    updated_at: '2026-10-12T00:05:00Z',
  },
];

describe('Chat-First Product Hierarchy Tests', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it('renders Header with The Lenny Growth Assistant identity and tabs', () => {
    const handleSelectView = vi.fn();
    render(
      <Header
        currentView="chat"
        onSelectView={handleSelectView}
        hasActiveArtifact={false}
      />
    );

    expect(screen.getByText(/The Lenny Growth Assistant/i)).toBeInTheDocument();
    expect(screen.getByText(/Podcast Intelligence/i)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Chat/i })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Artifacts & Library/i })).toBeInTheDocument();
  });

  it('renders ChatView empty state with suggested questions', () => {
    const handleSend = vi.fn();
    const handleEssay = vi.fn();

    render(
      <ChatView
        sessionId="sess-123"
        messages={[]}
        isLoading={false}
        onSendMessage={handleSend}
        onEssayCreated={handleEssay}
      />
    );

    expect(screen.getByText(/Ask product, growth and startup questions/i)).toBeInTheDocument();
    expect(screen.getByText(/Suggested Questions/i)).toBeInTheDocument();
    expect(screen.getByText(/How do I measure product-market fit\?/i)).toBeInTheDocument();

    // Clicking suggested prompt triggers send
    const promptBtn = screen.getByText(/How do I measure product-market fit\?/i);
    fireEvent.click(promptBtn);
    expect(handleSend).toHaveBeenCalledWith('How do I measure product-market fit?', 'rag');
  });

  it('renders grounded assistant message with SourcesSection and verified YouTube links', () => {
    const handleSend = vi.fn();
    const handleEssay = vi.fn();

    render(
      <ChatView
        sessionId="sess-123"
        messages={mockMessages}
        isLoading={false}
        onSendMessage={handleSend}
        onEssayCreated={handleEssay}
      />
    );

    // User message
    expect(screen.getByText(/What is Rahul Vohra product market fit framework\?/i)).toBeInTheDocument();
    // Assistant message
    expect(screen.getByText(/Rahul Vohra measured PMF with the 40% threshold/i)).toBeInTheDocument();
    // Source details
    expect(screen.getByText(/Verified Sources from Lenny's Podcast/i)).toBeInTheDocument();
    expect(screen.getAllByText(/Rahul Vohra/i).length).toBeGreaterThanOrEqual(2);
    expect(screen.getAllByText(/00:02:15/i).length).toBeGreaterThanOrEqual(1);

    // Verified YouTube deep link
    const ytLink = screen.getByRole('link', { name: /Watch Episode \(00:02:15\)/i });
    expect(ytLink).toBeInTheDocument();
    expect(ytLink).toHaveAttribute('href', 'https://www.youtube.com/watch?v=l-T8sNRcWQk&t=135s');
    expect(ytLink).toHaveAttribute('target', '_blank');

    // Contextual actions
    expect(screen.getByRole('button', { name: /Create essay/i })).toBeInTheDocument();
  });

  it('renders Sidebar with recent sessions and allows selection', () => {
    const handleSelect = vi.fn();
    const handleNew = vi.fn();
    const handleLib = vi.fn();
    const handleToggle = vi.fn();

    render(
      <Sidebar
        sessions={mockSessions}
        activeSessionId="sess-123"
        isOpen={true}
        onToggleOpen={handleToggle}
        onSelectSession={handleSelect}
        onNewChat={handleNew}
        onOpenLibrary={handleLib}
        isLibraryActive={false}
        providerInfo={{ provider: 'ollama', model: 'qwen2.5:1.5b' }}
      />
    );

    expect(screen.getByText(/Product Market Fit Framework/i)).toBeInTheDocument();
    expect(screen.getByText(/Growth team structure/i)).toBeInTheDocument();
    expect(screen.getByText(/Active model: Ollama · qwen2.5:1.5b/i)).toBeInTheDocument();

    fireEvent.click(screen.getByText(/Growth team structure/i));
    expect(handleSelect).toHaveBeenCalledWith('sess-456');

    fireEvent.click(screen.getByRole('button', { name: /New Chat/i }));
    expect(handleNew).toHaveBeenCalled();
  });

  it('renders EssayDialog when requested and submits brief with target word count', async () => {
    const handleClose = vi.fn();
    const handleCreated = vi.fn();

    vi.spyOn(apiClient, 'submitEssay').mockResolvedValueOnce({
      job_id: 'job-123',
      status: 'queued',
      stage: 'Queued',
      topic: 'PMF Engine',
      target_word_count: 650,
      artifact_id: null,
      version_number: null,
      error: null,
      elapsed_seconds: 0.1,
    });

    vi.spyOn(apiClient, 'getJobStatus').mockResolvedValueOnce({
      job_id: 'job-123',
      status: 'completed',
      stage: 'Completed',
      topic: 'PMF Engine',
      target_word_count: 650,
      artifact_id: 'art-999',
      version_number: 1,
      error: null,
      elapsed_seconds: 45.0,
    });

    vi.spyOn(apiClient, 'getArtifact').mockResolvedValueOnce({
      id: 'art-999',
      session_id: 'sess-123',
      title: 'PMF Engine',
      artifact_type: 'essay',
      status: 'completed',
      created_at: '2026-10-12T00:00:00Z',
      updated_at: '2026-10-12T00:00:00Z',
      latest_version: {
        id: 'ver-999',
        artifact_id: 'art-999',
        version_number: 1,
        markdown_content: '# PMF Engine',
        html_content: '<h1>PMF Engine</h1>',
        word_count: 640,
        writing_brief: { topic: 'PMF Engine' },
        sources: [],
        eval_metadata: { passed: true },
        model_metadata: {},
        created_at: '2026-10-12T00:00:00Z',
      },
    });

    render(
      <EssayDialog
        initialTopic="PMF Engine"
        sessionId="sess-123"
        isOpen={true}
        onClose={handleClose}
        onEssayCreated={handleCreated}
      />
    );

    expect(screen.getByRole('heading', { name: /Create Essay/i })).toBeInTheDocument();
    const submitBtn = screen.getByRole('button', { name: /Create Essay/i });
    fireEvent.click(submitBtn);

    await waitFor(() => {
      expect(apiClient.submitEssay).toHaveBeenCalled();
      expect(handleCreated).toHaveBeenCalled();
      expect(handleClose).toHaveBeenCalled();
    });
  });

  it('renders Sidebar with an independently scrollable history container', () => {
    const handleSelect = vi.fn();
    const handleNew = vi.fn();
    const handleToggle = vi.fn();
    const handleOpenLib = vi.fn();

    const { container } = render(
      <Sidebar
        sessions={mockSessions}
        activeSessionId="sess-123"
        isOpen={true}
        onToggleOpen={handleToggle}
        onSelectSession={handleSelect}
        onNewChat={handleNew}
        onOpenLibrary={handleOpenLib}
        isLibraryActive={false}
      />
    );

    const aside = container.querySelector('aside.app-sidebar');
    expect(aside).toBeInTheDocument();
    expect(aside).toHaveStyle({ height: '100%' });

    // The session list container has overflow-y: auto and min-height: 0
    const scrollContainer = aside?.querySelector('div[style*="overflow-y: auto"], div[style*="overflowY: auto"]');
    expect(scrollContainer).toBeInTheDocument();
    expect(screen.getByText('Product Market Fit Framework')).toBeInTheDocument();
  });

  it('contains ChatView with a scrollable messages region and anchored input bar', () => {
    const handleSend = vi.fn();
    const handleEssay = vi.fn();

    const { container } = render(
      <ChatView
        sessionId="sess-123"
        messages={mockMessages}
        isLoading={false}
        onSendMessage={handleSend}
        onEssayCreated={handleEssay}
      />
    );

    const chatView = container.querySelector('.chat-view');
    expect(chatView).toBeInTheDocument();
    expect(chatView).toHaveStyle({ height: '100%', overflow: 'hidden' });

    // Messages container has independent overflowY auto
    const messagesRegion = chatView?.querySelector('div[style*="overflow-y: auto"], div[style*="overflowY: auto"]');
    expect(messagesRegion).toBeInTheDocument();

    // Input composer is present within the chat workspace
    const inputArea = screen.getByLabelText(/User query input/i);
    expect(inputArea).toBeInTheDocument();
  });

  it('renders Create artifact and Create HTML snippet buttons and invokes callback', () => {
    const handleSend = vi.fn();
    const handleEssay = vi.fn();
    const handleCreateArtifact = vi.fn();

    render(
      <ChatView
        sessionId="sess-123"
        messages={mockMessages}
        isLoading={false}
        onSendMessage={handleSend}
        onEssayCreated={handleEssay}
        onCreateArtifactFromChat={handleCreateArtifact}
      />
    );

    const createDocBtn = screen.getByRole('button', { name: /Create artifact/i });
    const createHtmlBtn = screen.getByRole('button', { name: /Create HTML snippet/i });

    expect(createDocBtn).toBeInTheDocument();
    expect(createHtmlBtn).toBeInTheDocument();

    fireEvent.click(createDocBtn);
    expect(handleCreateArtifact).toHaveBeenCalledWith(
      expect.stringContaining('What is Rahul Vohra'),
      mockMessages[1].content,
      'document'
    );

    fireEvent.click(createHtmlBtn);
    expect(handleCreateArtifact).toHaveBeenCalledWith(
      expect.stringContaining('What is Rahul Vohra'),
      mockMessages[1].content,
      'html'
    );
  });

  it('renders integrated viewer beside chat in split-panel layout and preserves chat history', async () => {
    vi.spyOn(apiClient, 'getHealthReady').mockResolvedValue({
      status: 'ok',
      inference: { provider: 'ollama', configured_model: 'qwen2.5:1.5b' },
    } as any);

    vi.spyOn(apiClient, 'listSessions').mockResolvedValue({
      sessions: mockSessions,
      total_count: 2,
    });

    vi.spyOn(apiClient, 'getSessionMessages').mockResolvedValue({
      session_id: 'sess-123',
      messages: mockMessages,
    });

    vi.spyOn(apiClient, 'createArtifact').mockResolvedValue({
      id: 'art-split-1',
      session_id: 'sess-123',
      title: 'Split Panel Test Artifact',
      artifact_type: 'document',
      status: 'completed',
      created_at: '2026-10-12T00:00:00Z',
      updated_at: '2026-10-12T00:00:00Z',
      latest_version: {
        id: 'ver-split-1',
        artifact_id: 'art-split-1',
        version_number: 1,
        markdown_content: '# Split Panel Test Artifact\n\nContent rendered beside chat.',
        html_content: '<div class="lenny-essay-preview"><h1>Split Panel Test Artifact</h1></div>',
        word_count: 50,
        writing_brief: { topic: 'Split Panel' },
        sources: [],
        eval_metadata: { passed: true },
        model_metadata: {},
        created_at: '2026-10-12T00:00:00Z',
      },
    });

    const { container } = render(<App />);

    // Wait for chat messages to load
    await waitFor(() => {
      expect(screen.getByText(/What is Rahul Vohra product market fit framework/i)).toBeInTheDocument();
    });

    // Click "Create artifact" button on the assistant message
    const createArtBtn = await screen.findByRole('button', { name: /Create artifact/i });
    fireEvent.click(createArtBtn);

    // Verify split container is rendered with both chat pane and artifact pane beside each other
    await waitFor(() => {
      expect(screen.getByTestId('chat-split-container')).toBeInTheDocument();
      expect(screen.getByTestId('chat-split-pane')).toBeInTheDocument();
      expect(screen.getByTestId('artifact-split-pane')).toBeInTheDocument();
    });

    // Verify chat messages remain visible beside the artifact
    expect(screen.getByText(/What is Rahul Vohra product market fit framework/i)).toBeInTheDocument();
    expect(screen.getByText('Split Panel Test Artifact')).toBeInTheDocument();

    // Verify user can return to conversation and chat history is preserved
    const backBtn = screen.getByRole('button', { name: /Back to Chat/i });
    fireEvent.click(backBtn);

    await waitFor(() => {
      expect(screen.queryByTestId('artifact-split-pane')).not.toBeInTheDocument();
    });

    // Chat history is fully preserved
    expect(screen.getByText(/What is Rahul Vohra product market fit framework/i)).toBeInTheDocument();
  });
});


import React, { useState, useEffect } from 'react';
import { Header } from './components/Header';
import { Sidebar } from './components/Sidebar';
import { ChatView } from './components/ChatView';
import { Workspace } from './components/Workspace';
import { EssayLibrary } from './components/EssayLibrary';
import { apiClient } from './api/client';
import type { ChatMessage, ChatSession, LLMSettingsResponse, ModelConfigResponse, WritingArtifactResponse } from './api/types';

export const App: React.FC = () => {
  const [currentView, setCurrentView] = useState<'chat' | 'library' | 'workspace'>('chat');
  const [sessions, setSessions] = useState<ChatSession[]>([]);
  const [activeSessionId, setActiveSessionId] = useState<string | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [isLoadingMessages, setIsLoadingMessages] = useState<boolean>(false);
  const [isGenerating, setIsGenerating] = useState<boolean>(false);
  const [sidebarOpen, setSidebarOpen] = useState<boolean>(() =>
    typeof window !== 'undefined' ? window.innerWidth > 768 : true
  );
  const [activeArtifact, setActiveArtifact] = useState<WritingArtifactResponse | null>(null);
  const [providerInfo, setProviderInfo] = useState<{ provider: string; model: string } | null>(null);
  const [modelConfig, setModelConfig] = useState<ModelConfigResponse | null>(null);
  const [llmSettings, setLlmSettings] = useState<LLMSettingsResponse | null>(null);

  // Load readiness status & model configuration
  const fetchModelConfig = async () => {
    try {
      const settings = await apiClient.getLLMSettings();
      setLlmSettings(settings);
      setProviderInfo({ provider: settings.active_provider, model: settings.active_model });
    } catch {
      try {
        const cfg = await apiClient.getModelConfig();
        setModelConfig(cfg);
        setProviderInfo({ provider: cfg.active_provider, model: cfg.active_model });
      } catch {
        try {
          const ready = await apiClient.getHealthReady();
          const inference = ready.inference || {};
          const provider = inference.provider || 'ollama';
          const model = inference.configured_model || 'qwen2.5:1.5b';
          setProviderInfo({ provider, model });
        } catch {
          setProviderInfo({ provider: 'ollama', model: 'qwen2.5:1.5b' });
        }
      }
    }
  };

  useEffect(() => {
    fetchModelConfig();
  }, []);

  const handleSwitchProvider = async (provider: 'ollama' | 'nvidia', model?: string) => {
    try {
      const updated = await apiClient.updateLLMSettings({ provider, model });
      setLlmSettings(updated);
      setProviderInfo({ provider: updated.active_provider, model: updated.active_model });
    } catch (err: any) {
      console.error('Failed to update LLM provider:', err);
      throw err;
    }
  };

  const handleTestProvider = async (provider: string) => {
    return await apiClient.testLLMConnection({ provider });
  };

  const handleSwitchModel = async (provider: 'ollama' | 'litellm' | 'nvidia', model?: string) => {
    try {
      if (provider === 'nvidia' || provider === 'ollama') {
        await handleSwitchProvider(provider, model);
      } else {
        const updated = await apiClient.switchModel({ provider, model });
        setModelConfig(updated);
        setProviderInfo({ provider: updated.active_provider, model: updated.active_model });
      }
    } catch (err: any) {
      alert(err.message || 'Failed to switch model provider');
    }
  };

  // Load recent sessions on initial mount
  useEffect(() => {
    const loadSessions = async () => {
      try {
        const resp = await apiClient.listSessions(30);
        setSessions(resp.sessions);
        if (resp.sessions.length > 0) {
          const first = resp.sessions[0];
          setActiveSessionId(first.id);
          loadSessionMessages(first.id);
        } else {
          // Create initial session
          handleNewChat();
        }
      } catch (err) {
        console.warn('Could not load sessions:', err);
      }
    };
    loadSessions();
  }, []);

  const loadSessionMessages = async (sessionId: string) => {
    setIsLoadingMessages(true);
    try {
      const resp = await apiClient.getSessionMessages(sessionId);
      setMessages(resp.messages);
    } catch (err) {
      console.warn('Could not load messages for session:', sessionId, err);
      setMessages([]);
    } finally {
      setIsLoadingMessages(false);
    }
  };

  const handleSelectSession = (sessionId: string) => {
    setActiveSessionId(sessionId);
    setCurrentView('chat');
    loadSessionMessages(sessionId);
    if (typeof window !== 'undefined' && window.innerWidth <= 768) {
      setSidebarOpen(false);
    }
  };

  const handleNewChat = async () => {
    try {
      const newSession = await apiClient.createSession();
      setSessions((prev) => [newSession, ...prev]);
      setActiveSessionId(newSession.id);
      setMessages([]);
      setCurrentView('chat');
    } catch (err) {
      console.error('Failed to create new chat session:', err);
    }
  };

  const handleSendMessage = async (text: string, orchestrator: 'rag' | 'pi') => {
    let targetSessionId = activeSessionId;

    if (!targetSessionId) {
      try {
        const newSession = await apiClient.createSession();
        setSessions((prev) => [newSession, ...prev]);
        setActiveSessionId(newSession.id);
        targetSessionId = newSession.id;
      } catch (err) {
        console.error('Failed to create session for message:', err);
        return;
      }
    }

    // Optimistic user message
    const tempUserMsg: ChatMessage = {
      id: Date.now(),
      session_id: targetSessionId,
      role: 'user',
      content: text,
      created_at: new Date().toISOString(),
    };
    setMessages((prev) => [...prev, tempUserMsg]);
    setIsGenerating(true);

    try {
      const asstResponse = await apiClient.sendChatMessage(targetSessionId, text, orchestrator);
      setMessages((prev) => [...prev, asstResponse]);

      // Refresh session list order
      try {
        const updatedList = await apiClient.listSessions(30);
        setSessions(updatedList.sessions);
      } catch {
        // Ignore session refresh failure
      }
    } catch (err: any) {
      const errorMsg: ChatMessage = {
        id: Date.now() + 1,
        session_id: targetSessionId,
        role: 'assistant',
        content: `Error: ${err.message || 'Unable to generate response. Please check model provider status.'}`,
        created_at: new Date().toISOString(),
      };
      setMessages((prev) => [...prev, errorMsg]);
    } finally {
      setIsGenerating(false);
    }
  };

  const [isArtifactPanelOpen, setIsArtifactPanelOpen] = useState<boolean>(false);

  const handleEssayCreated = (artifact: WritingArtifactResponse) => {
    setActiveArtifact(artifact);
    setIsArtifactPanelOpen(true);
    setCurrentView('chat');
  };

  const handleOpenArtifact = (artifact: WritingArtifactResponse) => {
    setActiveArtifact(artifact);
    setIsArtifactPanelOpen(true);
    setCurrentView('chat');
  };

  const handleBackToChat = () => {
    setIsArtifactPanelOpen(false);
    setCurrentView('chat');
  };

  const handleToggleExpandWorkspace = () => {
    setCurrentView((prev) => (prev === 'workspace' ? 'chat' : 'workspace'));
  };

  const handleCreateArtifactFromChat = async (
    title: string,
    content: string,
    type: 'document' | 'html' = 'document'
  ) => {
    try {
      const created = await apiClient.createArtifact({
        title,
        content,
        artifact_type: type,
        session_id: activeSessionId || undefined,
      });
      setActiveArtifact(created);
      setIsArtifactPanelOpen(true);
      setCurrentView('chat');
    } catch (err) {
      console.warn('Backend createArtifact failed, falling back to local artifact:', err);
      const syntheticArtifact: WritingArtifactResponse = {
        id: `synth-${Date.now()}`,
        session_id: activeSessionId,
        title,
        artifact_type: type,
        status: 'completed',
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
        latest_version: {
          id: `synth-v1-${Date.now()}`,
          artifact_id: `synth-${Date.now()}`,
          version_number: 1,
          markdown_content:
            type === 'html' ? `# ${title}\n\n\`\`\`html\n${content}\n\`\`\`` : `# ${title}\n\n${content}`,
          html_content:
            type === 'html'
              ? content
              : `<div class="lenny-essay-preview"><h1>${title}</h1><p>${content}</p></div>`,
          word_count: content.split(/\s+/).filter(Boolean).length,
          writing_brief: { topic: title },
          sources: [],
          eval_metadata: { passed: true },
          model_metadata: { author: 'conversation_export' },
          created_at: new Date().toISOString(),
        },
      };
      setActiveArtifact(syntheticArtifact);
      setIsArtifactPanelOpen(true);
      setCurrentView('chat');
    }
  };

  return (
    <div className="app-layout">
      <Header
        currentView={currentView}
        onSelectView={(view) => setCurrentView(view)}
        onToggleSidebar={() => setSidebarOpen(!sidebarOpen)}
        hasActiveArtifact={activeArtifact !== null && isArtifactPanelOpen}
        onBackToChat={handleBackToChat}
        llmSettings={llmSettings}
        onSwitchProvider={handleSwitchProvider}
        onTestProvider={handleTestProvider}
        modelConfig={modelConfig}
        onSwitchModel={handleSwitchModel}
      />

      <div className="chat-app-body">
        {/* Left Navigation Sidebar */}
        <Sidebar
          sessions={sessions}
          activeSessionId={activeSessionId}
          isOpen={sidebarOpen}
          onToggleOpen={() => setSidebarOpen(!sidebarOpen)}
          onSelectSession={handleSelectSession}
          onNewChat={handleNewChat}
          onOpenLibrary={() => setCurrentView('library')}
          isLibraryActive={currentView === 'library'}
          providerInfo={providerInfo}
        />

        {/* Main Content Area */}
        <main style={{ flex: '1 1 0%', minWidth: 0, minHeight: 0, display: 'flex', flexDirection: 'column', height: '100%', overflow: 'hidden' }}>
          {currentView === 'library' ? (
            <div style={{ flex: '1 1 0%', minHeight: 0, minWidth: 0, overflowY: 'auto', height: '100%' }}>
              <EssayLibrary
                onOpenArtifact={handleOpenArtifact}
                onBackToChat={handleBackToChat}
              />
            </div>
          ) : currentView === 'workspace' && activeArtifact ? (
            <div style={{ flex: '1 1 0%', minHeight: 0, minWidth: 0, display: 'flex', flexDirection: 'column', height: '100%', overflow: 'hidden' }}>
              <Workspace
                artifact={activeArtifact}
                onArtifactUpdated={(updated) => setActiveArtifact(updated)}
                onBackToChat={handleBackToChat}
                isExpanded={true}
                onToggleExpand={handleToggleExpandWorkspace}
              />
            </div>
          ) : (
            <div
              className="chat-split-container"
              data-testid="chat-split-container"
              style={{
                flex: '1 1 0%',
                minHeight: 0,
                minWidth: 0,
                height: '100%',
                overflow: 'hidden',
              }}
            >
              {/* Chat View */}
              <div
                className={`chat-split-pane ${isArtifactPanelOpen && activeArtifact ? 'has-split' : 'full-width'}`}
                data-testid="chat-split-pane"
                style={{
                  height: '100%',
                  display: 'flex',
                  flexDirection: 'column',
                  overflow: 'hidden',
                  transition: 'flex 0.2s ease',
                }}
              >
                <ChatView
                  sessionId={activeSessionId}
                  messages={messages}
                  isLoading={isGenerating || isLoadingMessages}
                  onSendMessage={handleSendMessage}
                  onEssayCreated={handleEssayCreated}
                  onCreateArtifactFromChat={handleCreateArtifactFromChat}
                />
              </div>

              {/* In-app Integrated Artifact Viewer Beside Chat */}
              {isArtifactPanelOpen && activeArtifact && (
                <div
                  className="artifact-split-pane"
                  data-testid="artifact-split-pane"
                  style={{
                    height: '100%',
                    display: 'flex',
                    flexDirection: 'column',
                    overflow: 'hidden',
                    backgroundColor: 'var(--bg-surface)',
                  }}
                >
                  <Workspace
                    artifact={activeArtifact}
                    onArtifactUpdated={(updated) => setActiveArtifact(updated)}
                    onBackToChat={handleBackToChat}
                    isExpanded={false}
                    onToggleExpand={handleToggleExpandWorkspace}
                  />
                </div>
              )}
            </div>
          )}
        </main>
      </div>
    </div>
  );
};

export default App;

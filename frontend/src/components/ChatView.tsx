import React, { useState, useRef, useEffect } from 'react';
import { Send, Sparkles, FileText, FileCode, Loader2, Bot, User, ArrowRight } from 'lucide-react';
import { SourcesSection } from './SourcesSection';
import { EssayDialog } from './EssayDialog';
import type { ChatMessage, WritingArtifactResponse } from '../api/types';

interface ChatViewProps {
  sessionId: string | null;
  messages: ChatMessage[];
  isLoading: boolean;
  onSendMessage: (text: string, orchestrator: 'rag' | 'pi') => Promise<void>;
  onEssayCreated: (artifact: WritingArtifactResponse) => void;
  onCreateArtifactFromChat?: (title: string, content: string, type?: 'document' | 'html') => void;
}

const SUGGESTED_QUESTIONS = [
  'How do I measure product-market fit?',
  'What makes a growth team effective?',
  'How should a startup improve user onboarding?',
  "What growth lessons can be learned from Lenny's Podcast?",
];

export const ChatView: React.FC<ChatViewProps> = ({
  sessionId,
  messages,
  isLoading,
  onSendMessage,
  onEssayCreated,
  onCreateArtifactFromChat,
}) => {
  const [inputText, setInputText] = useState<string>('');
  const [orchestrator, setOrchestrator] = useState<'rag' | 'pi'>('rag');
  const [essayDialogOpen, setEssayDialogOpen] = useState<boolean>(false);
  const [essayTopic, setEssayTopic] = useState<string>('');
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    if (typeof messagesEndRef.current?.scrollIntoView === 'function') {
      messagesEndRef.current.scrollIntoView({ behavior: 'smooth' });
    }
  }, [messages, isLoading]);

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSubmit();
    }
  };

  const handleSubmit = async (textToSend?: string) => {
    const text = (textToSend || inputText).trim();
    if (!text || isLoading) return;

    setInputText('');
    if (textareaRef.current) {
      textareaRef.current.style.height = 'auto';
    }
    await onSendMessage(text, orchestrator);
  };

  const handleOpenEssayDialog = (topicSuggestion: string) => {
    setEssayTopic(topicSuggestion);
    setEssayDialogOpen(true);
  };

  return (
    <div
      className="chat-view"
      style={{
        display: 'flex',
        flexDirection: 'column',
        height: '100%',
        minHeight: 0,
        minWidth: 0,
        width: '100%',
        backgroundColor: 'var(--bg-page)',
        position: 'relative',
        overflow: 'hidden',
      }}
    >
      {/* Messages Scroll Area */}
      <div
        style={{
          flex: '1 1 0%',
          minHeight: 0,
          minWidth: 0,
          overflowY: 'auto',
          overflowX: 'hidden',
          padding: '1.5rem 1.25rem 7.5rem',
          display: 'flex',
          flexDirection: 'column',
          gap: '1.5rem',
          maxWidth: '860px',
          margin: '0 auto',
          width: '100%',
        }}
      >
        {messages.length === 0 ? (
          /* Empty State / Welcome Screen */
          <div
            style={{
              display: 'flex',
              flexDirection: 'column',
              alignItems: 'center',
              justifyContent: 'center',
              minHeight: '60vh',
              textAlign: 'center',
              padding: '2rem 1rem',
            }}
          >
            <div
              style={{
                width: '56px',
                height: '56px',
                borderRadius: '16px',
                backgroundColor: 'var(--primary-light)',
                color: 'var(--primary)',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                marginBottom: '1.25rem',
                boxShadow: 'var(--shadow-sm)',
              }}
            >
              <Sparkles size={28} />
            </div>

            <h1
              style={{
                fontFamily: 'Newsreader, Georgia, serif',
                fontSize: '2.1rem',
                fontWeight: 700,
                color: 'var(--text-main)',
                marginBottom: '0.65rem',
                lineHeight: 1.2,
              }}
            >
              The Lenny Growth Assistant
            </h1>

            <p
              style={{
                fontSize: '1.05rem',
                color: 'var(--text-secondary)',
                maxWidth: '560px',
                lineHeight: 1.6,
                marginBottom: '2rem',
              }}
            >
              Ask product, growth and startup questions. Get answers grounded in Lenny's Podcast, with traceable sources and reusable artifacts.
            </p>

            <div style={{ width: '100%', maxWidth: '640px' }}>
              <div
                style={{
                  fontSize: '0.8rem',
                  fontWeight: 700,
                  textTransform: 'uppercase',
                  letterSpacing: '0.05em',
                  color: 'var(--text-muted)',
                  marginBottom: '0.75rem',
                  textAlign: 'left',
                }}
              >
                Suggested Questions
              </div>

              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '0.75rem' }}>
                {SUGGESTED_QUESTIONS.map((question, i) => (
                  <button
                    key={i}
                    type="button"
                    onClick={() => handleSubmit(question)}
                    style={{
                      textAlign: 'left',
                      padding: '0.85rem 1rem',
                      backgroundColor: 'var(--bg-surface)',
                      border: '1px solid var(--border-light)',
                      borderRadius: 'var(--radius-md)',
                      color: 'var(--text-main)',
                      fontSize: '0.875rem',
                      cursor: 'pointer',
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'space-between',
                      gap: '0.5rem',
                      boxShadow: 'var(--shadow-sm)',
                      transition: 'all 0.15s ease',
                    }}
                    onMouseEnter={(e) => {
                      e.currentTarget.style.borderColor = 'var(--primary-border)';
                      e.currentTarget.style.backgroundColor = 'var(--bg-surface)';
                    }}
                    onMouseLeave={(e) => {
                      e.currentTarget.style.borderColor = 'var(--border-light)';
                    }}
                  >
                    <span style={{ fontWeight: 500 }}>{question}</span>
                    <ArrowRight size={14} style={{ color: 'var(--primary)', flexShrink: 0 }} />
                  </button>
                ))}
              </div>
            </div>
          </div>
        ) : (
          /* Message Stream */
          messages.map((msg, index) => {
            const isUser = msg.role === 'user';

            return (
              <div
                key={msg.id || index}
                style={{
                  display: 'flex',
                  flexDirection: 'column',
                  alignItems: isUser ? 'flex-end' : 'flex-start',
                  width: '100%',
                }}
              >
                <div
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    gap: '0.45rem',
                    marginBottom: '0.35rem',
                    fontSize: '0.75rem',
                    color: 'var(--text-muted)',
                  }}
                >
                  {isUser ? (
                    <>
                      <span style={{ fontWeight: 600 }}>You</span>
                      <User size={12} />
                    </>
                  ) : (
                    <>
                      <Bot size={13} style={{ color: 'var(--primary)' }} />
                      <span style={{ fontWeight: 600, color: 'var(--text-secondary)' }}>The Lenny Assistant</span>
                      {msg.model && (
                        <span
                          style={{
                            fontSize: '0.7rem',
                            padding: '0.1rem 0.4rem',
                            borderRadius: 'var(--radius-sm)',
                            backgroundColor: 'var(--bg-subtle)',
                            fontFamily: 'var(--font-mono)',
                          }}
                        >
                          {msg.provider ? `${msg.provider} · ${msg.model}` : msg.model}
                        </span>
                      )}
                    </>
                  )}
                </div>

                <div
                  style={{
                    maxWidth: '85%',
                    backgroundColor: isUser ? 'var(--primary)' : 'var(--bg-surface)',
                    color: isUser ? '#ffffff' : 'var(--text-main)',
                    padding: '1rem 1.25rem',
                    borderRadius: isUser ? '16px 16px 4px 16px' : '16px 16px 16px 4px',
                    boxShadow: 'var(--shadow-sm)',
                    border: isUser ? 'none' : '1px solid var(--border-light)',
                    fontSize: '0.95rem',
                    lineHeight: 1.65,
                    whiteSpace: 'pre-wrap',
                    wordBreak: 'break-word',
                  }}
                >
                  {msg.content}

                  {/* Sources Section directly below grounded assistant answer */}
                  {!isUser && msg.sources && msg.sources.length > 0 && (
                    <SourcesSection sources={msg.sources} />
                  )}

                  {/* Secondary Contextual Actions for Assistant Messages */}
                  {!isUser && (
                    <div
                      style={{
                        display: 'flex',
                        alignItems: 'center',
                        flexWrap: 'wrap',
                        gap: '0.5rem',
                        marginTop: '1rem',
                        paddingTop: '0.75rem',
                        borderTop: '1px solid var(--border-light)',
                      }}
                    >
                      <button
                        type="button"
                        onClick={() => {
                          const topicGuess = messages[index - 1]?.content || 'Product Growth Strategy';
                          handleOpenEssayDialog(topicGuess);
                        }}
                        style={{
                          display: 'inline-flex',
                          alignItems: 'center',
                          gap: '0.35rem',
                          padding: '0.35rem 0.75rem',
                          borderRadius: 'var(--radius-sm)',
                          backgroundColor: 'var(--primary-light)',
                          color: 'var(--primary)',
                          border: '1px solid var(--primary-border)',
                          fontSize: '0.775rem',
                          fontWeight: 600,
                          cursor: 'pointer',
                        }}
                      >
                        <FileText size={13} />
                        <span>Create essay</span>
                      </button>

                      {onCreateArtifactFromChat && (
                        <>
                          <button
                            type="button"
                            onClick={() => {
                              const title = messages[index - 1]?.content.slice(0, 50) || 'Grounded Growth Document';
                              onCreateArtifactFromChat(title, msg.content, 'document');
                            }}
                            style={{
                              display: 'inline-flex',
                              alignItems: 'center',
                              gap: '0.35rem',
                              padding: '0.35rem 0.75rem',
                              borderRadius: 'var(--radius-sm)',
                              backgroundColor: 'var(--bg-subtle)',
                              color: 'var(--text-secondary)',
                              border: '1px solid var(--border-medium)',
                              fontSize: '0.775rem',
                              fontWeight: 500,
                              cursor: 'pointer',
                            }}
                          >
                            <Sparkles size={13} />
                            <span>Create artifact</span>
                          </button>

                          <button
                            type="button"
                            onClick={() => {
                              const title = messages[index - 1]?.content.slice(0, 50) || 'Grounded Growth HTML Snippet';
                              onCreateArtifactFromChat(title, msg.content, 'html');
                            }}
                            style={{
                              display: 'inline-flex',
                              alignItems: 'center',
                              gap: '0.35rem',
                              padding: '0.35rem 0.75rem',
                              borderRadius: 'var(--radius-sm)',
                              backgroundColor: 'var(--bg-subtle)',
                              color: 'var(--text-secondary)',
                              border: '1px solid var(--border-medium)',
                              fontSize: '0.775rem',
                              fontWeight: 500,
                              cursor: 'pointer',
                            }}
                          >
                            <FileCode size={13} />
                            <span>Create HTML snippet</span>
                          </button>
                        </>
                      )}
                    </div>
                  )}
                </div>
              </div>
            );
          })
        )}

        {/* Loading Indicator */}
        {isLoading && (
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.6rem', color: 'var(--text-muted)', fontSize: '0.85rem' }}>
            <Loader2 size={16} className="spin-animation" style={{ color: 'var(--primary)' }} />
            <span>Consulting Lenny's Podcast archives and synthesizing grounded response...</span>
          </div>
        )}

        <div ref={messagesEndRef} />
      </div>

      {/* Fixed Bottom Input Area */}
      <div
        style={{
          position: 'absolute',
          bottom: 0,
          left: 0,
          right: 0,
          padding: '1rem 1.25rem',
          backgroundColor: 'var(--bg-surface)',
          borderTop: '1px solid var(--border-light)',
          boxShadow: '0 -4px 12px rgba(0, 0, 0, 0.03)',
        }}
      >
        <div style={{ maxWidth: '860px', margin: '0 auto', display: 'flex', flexDirection: 'column', gap: '0.5rem' }}>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', fontSize: '0.75rem', color: 'var(--text-muted)' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
              <span>Orchestrator:</span>
              <button
                type="button"
                onClick={() => setOrchestrator(orchestrator === 'rag' ? 'pi' : 'rag')}
                style={{
                  background: 'none',
                  border: '1px solid var(--border-medium)',
                  borderRadius: 'var(--radius-sm)',
                  padding: '0.15rem 0.5rem',
                  fontSize: '0.72rem',
                  cursor: 'pointer',
                  fontWeight: 600,
                  backgroundColor: orchestrator === 'pi' ? 'var(--primary-light)' : 'var(--bg-subtle)',
                  color: orchestrator === 'pi' ? 'var(--primary)' : 'var(--text-secondary)',
                }}
              >
                {orchestrator === 'rag' ? 'Direct RAG (Default)' : 'Pi Agent (Deep Tool Search)'}
              </button>
            </div>
            <span>Press Enter to send, Shift+Enter for new line</span>
          </div>

          <div
            style={{
              display: 'flex',
              alignItems: 'flex-end',
              gap: '0.6rem',
              backgroundColor: 'var(--bg-page)',
              border: '1px solid var(--border-medium)',
              borderRadius: 'var(--radius-lg)',
              padding: '0.45rem 0.65rem 0.45rem 0.85rem',
              boxShadow: 'var(--shadow-sm)',
            }}
          >
            <textarea
              ref={textareaRef}
              rows={1}
              value={inputText}
              onChange={(e) => {
                setInputText(e.target.value);
                e.target.style.height = 'auto';
                e.target.style.height = `${Math.min(e.target.scrollHeight, 160)}px`;
              }}
              onKeyDown={handleKeyDown}
              disabled={isLoading}
              placeholder="Ask anything about product management, growth, retention, hiring, or startup frameworks..."
              style={{
                flex: 1,
                border: 'none',
                background: 'transparent',
                resize: 'none',
                fontSize: '0.925rem',
                color: 'var(--text-main)',
                fontFamily: 'inherit',
                outline: 'none',
                maxHeight: '160px',
                lineHeight: 1.5,
                padding: '0.35rem 0',
              }}
              aria-label="User query input"
            />

            <button
              type="button"
              onClick={() => handleSubmit()}
              disabled={isLoading || !inputText.trim()}
              className="btn-primary"
              style={{
                padding: '0.55rem',
                borderRadius: 'var(--radius-md)',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                flexShrink: 0,
                cursor: isLoading || !inputText.trim() ? 'not-allowed' : 'pointer',
                opacity: isLoading || !inputText.trim() ? 0.5 : 1,
              }}
              aria-label="Send message"
            >
              <Send size={16} />
            </button>
          </div>
        </div>
      </div>

      {/* Contextual Ship 30 for 30 Essay Generation Dialog */}
      <EssayDialog
        initialTopic={essayTopic}
        sessionId={sessionId}
        isOpen={essayDialogOpen}
        onClose={() => setEssayDialogOpen(false)}
        onEssayCreated={onEssayCreated}
      />
    </div>
  );
};

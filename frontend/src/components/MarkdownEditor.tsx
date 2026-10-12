import React from 'react';

interface MarkdownEditorProps {
  content: string;
  onChange: (value: string) => void;
  onSave?: () => void;
  disabled?: boolean;
}

export const MarkdownEditor: React.FC<MarkdownEditorProps> = ({
  content,
  onChange,
  onSave,
  disabled = false,
}) => {
  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    // Save shortcut: Ctrl+S or Cmd+S
    if ((e.ctrlKey || e.metaKey) && e.key === 's') {
      e.preventDefault();
      if (onSave) {
        onSave();
      }
    }
  };

  return (
    <textarea
      className="markdown-textarea"
      value={content}
      onChange={(e) => onChange(e.target.value)}
      onKeyDown={handleKeyDown}
      disabled={disabled}
      placeholder="Write your Markdown essay here..."
      spellCheck={false}
      aria-label="Markdown Essay Editor"
    />
  );
};

import React, { useEffect, useRef } from 'react';

interface HtmlPreviewProps {
  htmlContent: string;
}

export const HtmlPreview: React.FC<HtmlPreviewProps> = ({ htmlContent }) => {
  const iframeRef = useRef<HTMLIFrameElement>(null);

  useEffect(() => {
    const iframe = iframeRef.current;
    if (!iframe) return;

    // Use srcdoc with rich editorial typography and comfortable reading measure
    const fullHtml = `
      <!DOCTYPE html>
      <html lang="en">
      <head>
        <meta charset="utf-8">
        <meta name="viewport" content="width=device-width, initial-scale=1">
        <style>
          :root {
            color-scheme: light;
          }
          *, *::before, *::after {
            box-sizing: border-box;
          }
          body {
            margin: 0;
            padding: 3rem 1.5rem;
            background: #ffffff;
            color: #1e293b;
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
            font-size: 1.05rem;
            line-height: 1.75;
            -webkit-font-smoothing: antialiased;
            -moz-osx-font-smoothing: grayscale;
          }
          .article-container {
            max-width: 68ch;
            margin: 0 auto;
          }
          h1, h2, h3, h4, h5, h6 {
            color: #0f172a;
            font-weight: 700;
            line-height: 1.3;
            letter-spacing: -0.02em;
          }
          h1 {
            font-size: 2.1rem;
            margin-top: 0;
            margin-bottom: 1.5rem;
            letter-spacing: -0.025em;
            line-height: 1.2;
          }
          h2 {
            font-size: 1.45rem;
            margin-top: 2.5rem;
            margin-bottom: 1rem;
            padding-bottom: 0.4rem;
            border-bottom: 1px solid #f1f5f9;
          }
          h3 {
            font-size: 1.2rem;
            margin-top: 2rem;
            margin-bottom: 0.75rem;
          }
          p {
            margin-top: 0;
            margin-bottom: 1.4rem;
          }
          a {
            color: #4f46e5;
            text-decoration: underline;
            text-underline-offset: 3px;
          }
          a:hover {
            color: #4338ca;
          }
          blockquote {
            border-left: 2px solid #cbd5e1;
            padding: 0.75rem 1.25rem;
            margin: 1.6rem 0;
            background: #f8fafc;
            border-radius: 0 4px 4px 0;
            color: #334155;
            font-style: italic;
          }
          blockquote p:last-child {
            margin-bottom: 0;
          }
          ul, ol {
            padding-left: 1.5rem;
            margin-top: 0;
            margin-bottom: 1.4rem;
          }
          li {
            margin-bottom: 0.4rem;
          }
          code {
            font-family: 'JetBrains Mono', 'Fira Code', Menlo, Monaco, Consolas, monospace;
            font-size: 0.88em;
            background: #f1f5f9;
            color: #312e81;
            padding: 0.15em 0.4em;
            border-radius: 4px;
            border: 1px solid #e2e8f0;
          }
          pre {
            background: #0f172a;
            color: #f8fafc;
            padding: 1.25rem;
            border-radius: 8px;
            overflow-x: auto;
            margin: 1.6rem 0;
          }
          pre code {
            background: transparent;
            color: inherit;
            border: none;
            padding: 0;
          }
          hr {
            border: none;
            border-top: 1px solid #e2e8f0;
            margin: 2.5rem 0;
          }
          table {
            width: 100%;
            border-collapse: collapse;
            margin: 1.6rem 0;
            font-size: 0.95rem;
          }
          th, td {
            border: 1px solid #e2e8f0;
            padding: 0.6rem 0.85rem;
            text-align: left;
          }
          th {
            background: #f8fafc;
            font-weight: 600;
            color: #0f172a;
          }
        </style>
      </head>
      <body>
        <div class="article-container">
          ${htmlContent}
        </div>
      </body>
      </html>
    `;

    iframe.srcdoc = fullHtml;
  }, [htmlContent]);

  return (
    <iframe
      ref={iframeRef}
      title="Essay HTML Preview"
      className="preview-iframe"
      // Restrictive security sandbox: strictly NO allow-scripts and NO allow-same-origin
      // Isolates DOM, prevents script execution, and prevents access to parent credentials or storage
      sandbox="allow-popups"
    />
  );
};

import '@testing-library/jest-dom'

// In Node/JSDOM test environment, ensure relative URLs resolve against local origin
// without hardcoding localhost in production browser client.ts.
const originalFetch = globalThis.fetch
if (originalFetch) {
  globalThis.fetch = async (input: RequestInfo | URL, init?: RequestInit) => {
    let urlStr = typeof input === 'string' ? input : input.toString()
    if (urlStr.startsWith('/')) {
      const resolvedUrl = new URL(urlStr, 'http://localhost:5173').toString()
      try {
        return await originalFetch(resolvedUrl, init)
      } catch (err: any) {
        // Provide safe fallback for unmocked secondary artifact version queries in tests
        if (urlStr.includes('/api/v1/writing/artifacts/') && urlStr.endsWith('/versions')) {
          return new Response(JSON.stringify({ artifact_id: 'test', title: 'Test', versions: [] }), {
            status: 200,
            headers: { 'Content-Type': 'application/json' },
          })
        }
        throw err
      }
    }
    return originalFetch(input, init)
  }
}

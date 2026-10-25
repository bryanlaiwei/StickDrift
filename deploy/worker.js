// Serves the built site (web/dist) and forwards /api/* to the FastAPI backend.
// The browser sees one origin, so the HttpOnly login cookie and the live WebSocket
// work the same way as through the Vite dev proxy (which also strips /api).
export default {
  async fetch(request, env) {
    const url = new URL(request.url)
    if (url.pathname !== '/api' && !url.pathname.startsWith('/api/')) {
      return env.ASSETS.fetch(request)
    }
    if (!env.BACKEND_URL) {
      return Response.json(
        { detail: 'The Stick Drift backend is not connected yet (BACKEND_URL is not set on the Worker).' },
        { status: 503 },
      )
    }
    const target = new URL(env.BACKEND_URL)
    target.pathname = target.pathname.replace(/\/$/, '') + (url.pathname.slice('/api'.length) || '/')
    target.search = url.search
    // Passing the original request keeps the method, body, cookies and WebSocket upgrade.
    return fetch(new Request(target, request))
  },
}

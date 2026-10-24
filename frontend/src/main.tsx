import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import AppRouter from '@app/router'
import { ErrorBoundary } from '@components/ErrorBoundary'
import { Toaster } from '@components/Toaster'
import { ThemeProvider } from '@app/theme/ThemeProvider'
import '@design/global.css'
import '@design/light-reconciliation.css'

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime:  60_000,
      retry:      1,
      refetchOnWindowFocus: false,
    },
  },
})

// A tab opened before a deploy (or during one) can ask for a chunk or stylesheet
// that was replaced.  Reload once to pick up the current build instead of
// leaving the error screen; the flag prevents a reload loop.
window.addEventListener('vite:preloadError', () => {
  try {
    if (sessionStorage.getItem('qentry_preload_reload')) return
    sessionStorage.setItem('qentry_preload_reload', '1')
  } catch { /* storage unavailable: still try once */ }
  window.location.reload()
})
window.addEventListener('load', () => {
  try { sessionStorage.removeItem('qentry_preload_reload') } catch { /* optional */ }
})

// Load optional typography after boot; a delayed font stylesheet must not
// prevent the application and its recovery message from appearing.
const fonts = document.createElement('link')
fonts.rel = 'stylesheet'
fonts.href = '/fonts/google/fonts.css'
document.head.appendChild(fonts)

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <ErrorBoundary>
      <ThemeProvider>
        <QueryClientProvider client={queryClient}>
          <AppRouter />
          <Toaster />
        </QueryClientProvider>
      </ThemeProvider>
    </ErrorBoundary>
  </StrictMode>,
)

import { Component, useEffect, type ReactNode } from 'react'
import { createRoot } from 'react-dom/client'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { useDesignMode } from '../src/features/events/components/invitations/hooks/useDesignMode'

// Import through Vite's normal graph so the hook and its provider share context.
export function mountDesignProbe(state: any, event: any): Promise<{ api: ReturnType<typeof useDesignMode>; unmount: () => void }> {
  const host = document.createElement('div')
  document.body.append(host)
  const root = createRoot(host)
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const unmount = () => { root.unmount(); client.clear(); host.remove() }
  return new Promise((resolve, reject) => {
    class Boundary extends Component<{ children: ReactNode }, { failed: boolean }> {
      state = { failed: false }
      static getDerivedStateFromError() { return { failed: true } }
      componentDidCatch(error: Error) { reject(error) }
      render() { return this.state.failed ? null : this.props.children }
    }
    function Probe() {
      const api = useDesignMode(state, event)
      useEffect(() => { resolve({ api, unmount }) }, [api])
      return null
    }
    root.render(<Boundary><QueryClientProvider client={client}><Probe /></QueryClientProvider></Boundary>)
  })
}

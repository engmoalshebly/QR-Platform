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

export async function mountFilesProbe(operationId: string) {
  const { OperationFiles } = await import('../src/features/events/components/invitations/GenerationOperationTracker')
  const host = document.createElement('div')
  host.id = 'files-probe'
  document.body.append(host)
  const root = createRoot(host)
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  root.render(<QueryClientProvider client={client}><OperationFiles operationId={operationId} /></QueryClientProvider>)
}

export async function mountMixedImportProbe() {
  const { ServerImportGenerate } = await import('../src/features/events/components/invitations/ServerImportPanel')
  const host = document.createElement('div'); host.id = 'mixed-import-probe'; document.body.append(host)
  const root = createRoot(host)
  const importer = {
    state: { summary: { total:2, valid:2, people:2, selected:2, selected_vip:1, selected_normal:1 }, deselected:[], analyzedRsvp:false, selectionReady:true },
    generate: async (body: unknown) => { (window as any).__mixedGeneration = body },
  } as any
  const templates = [{ id:'vip-template', name:'قالب كبار الضيوف', template_type:'designed', ticket_class:'vip', is_active:true },
    { id:'normal-template', name:'قالب العادي', template_type:'designed', ticket_class:'normal', is_active:true }] as any
  root.render(<ServerImportGenerate importer={importer} requireRsvp={false} layout={{}} designedLayout={{}} templates={templates} formats={['pdf']} maxCards={1000} forceDesigned />)
}

export async function mountDraftProbe() {
  const { useGenerationDraftRows } = await import('../src/features/events/hooks/useGenerationDraftRows')
  const host = document.createElement('div'); document.body.append(host)
  const root = createRoot(host)
  function Probe() {
    const draft = useGenerationDraftRows('test-event', 'quick', true)
    useEffect(() => { (window as any).__draftProbe = draft }, [draft])
    return <div id="draft-probe">{draft.loading ? 'loading' : draft.error || draft.rows.map(r => r.guest_name).join(',')}</div>
  }
  root.render(<Probe />)
}

export async function mountImportProbe() {
  const { useServerImport } = await import('../src/features/events/hooks/useServerImport')
  const host = document.createElement('div'); document.body.append(host)
  const root = createRoot(host)
  function Probe() {
    const importer = useServerImport('test-event', false, 'designed')
    useEffect(() => { (window as any).__importProbe = importer.state }, [importer.state])
    return <div id="import-probe">{importer.state.error || importer.state.fileName}</div>
  }
  root.render(<Probe />)
}

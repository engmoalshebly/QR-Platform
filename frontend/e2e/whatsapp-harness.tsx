import { createRoot } from 'react-dom/client'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { BrowserRouter } from 'react-router-dom'
import { useAuthStore } from '../src/features/auth/store/authStore'
import { WhatsAppSettings } from '../src/features/whatsapp/WhatsAppSettings'
import { EventRsvpTab } from '../src/features/events/components/EventRsvpTab'
import { EventFinalInvitationsTab } from '../src/features/events/components/EventFinalInvitationsTab'
import { setAccessToken } from '../src/services/http/client'

export function mountWhatsApp(permissions: string[], settings: boolean, final = false) {
 useAuthStore.setState({ currentTenantId:'tenant-one',permissions:new Set(permissions),tenants:[{tenant_id:'tenant-one',role:'member'} as never] })
 setAccessToken('test-token')
 document.getElementById('root')!.style.display='none'
 const host=document.createElement('div');document.body.append(host)
 const client=new QueryClient({defaultOptions:{queries:{retry:false}}})
 createRoot(host).render(<QueryClientProvider client={client}><BrowserRouter>{settings?<WhatsAppSettings />:<>{final?<EventFinalInvitationsTab event={{id:"event-one",title:"حفل الاختبار"}} />:<EventRsvpTab eventId="event-one" eventTitle="حفل الاختبار" />}</>}</BrowserRouter></QueryClientProvider>)
}

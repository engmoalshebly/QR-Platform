export function tablePayload(url:URL,rows:any[],summaries:any[]=[]){
 const purpose=(inv:any)=>inv.metadata?.require_rsvp && inv.rsvp_status!=='accepted'?'rsvp':'ticket'
 const states=(inv:any)=>summaries.find(d=>d.invitation_id===inv.id && d.purpose===purpose(inv))?.state || 'not_sent'
 const scope=rows.filter(inv=>url.searchParams.get('tab')!=='final' || inv.rsvp_status==='accepted')
 const search=(url.searchParams.get('search') || '').toLowerCase()
 const tc=url.searchParams.get('ticket_class') || 'all',rs=url.searchParams.get('rsvp_status') || 'all',ci=url.searchParams.get('checkin') || 'all',ws=url.searchParams.get('whatsapp_state') || 'all'
 const filtered=scope.filter(inv=>
  (!search || `${inv.guest_name} ${inv.guest_phone || ''}`.toLowerCase().includes(search)) &&
  (tc==='all'||inv.ticket_class===tc) && (rs==='all'||inv.rsvp_status===rs) &&
  (ci==='all'||(ci==='checked_in')===(inv.checkin_count>0)) &&
  (ws==='all'||(ws==='sent'?['sent','delivered','read'].includes(states(inv)):ws==='pending'?['queued','waiting_connection','sending'].includes(states(inv)):states(inv)===ws)))
 const limit=Number(url.searchParams.get('limit') || 50)
 const offset=Math.min(Number(url.searchParams.get('offset') || 0),Math.floor((Math.max(filtered.length,1)-1)/limit)*limit)
 const items=filtered.slice(offset,offset+limit)
 const accepted=scope.filter(inv=>inv.rsvp_status==='accepted').length,declined=scope.filter(inv=>inv.rsvp_status==='declined').length,vip=scope.filter(inv=>inv.ticket_class==='vip').length,checkedIn=scope.filter(inv=>inv.checkin_count>0).length
 return {items,total:filtered.length,limit,offset,stats:{total:scope.length,accepted,declined,pending:scope.length-accepted-declined,plusOnes:0,viewed:0,sent:0,unopened:0,vip,normal:scope.length-vip,checkedIn,remaining:scope.length-checkedIn},whatsapp:summaries.filter(d=>items.some(inv=>inv.id===d.invitation_id))}
}
export function historyPayload(items:any[],url:URL){
 const q=url.searchParams.get('search') || '',state=url.searchParams.get('state') || 'all',purpose=url.searchParams.get('purpose') || 'all',iid=url.searchParams.get('invitation_id')
 const filtered=items.filter(d=>(!iid||d.invitation_id===iid)&&(state==='all'||d.state===state)&&(purpose==='all'||d.purpose===purpose)&&(!q||`${d.guest_name} ${d.recipient}`.includes(q)))
 const limit=Number(url.searchParams.get('limit') || 50),offset=Number(url.searchParams.get('offset') || 0)
 return {items:filtered.slice(offset,offset+limit),total:filtered.length,limit,offset,as_of:'2026-10-12T15:10:00Z'}
}

export function messagePreviewPayload(rows:any[]){return {version:0,image_id:null,too_long:0,samples:rows.slice(0,1).map(inv=>({purpose:inv.rsvp_status==='accepted'?'ticket':'rsvp',guest_name:inv.guest_name,text:`مرحباً ${inv.guest_name}، ندعوك إلى حفل الاختبار.\nhttps://example.com/i/${inv.token}`}))}}

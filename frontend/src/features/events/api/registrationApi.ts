/**
 * registrationApi.ts
 * API layer for the Event Registration Form feature.
 */
import http from '@services/http/client'

export interface RegistrationFormField {
  id: string
  type: 'text' | 'number' | 'email' | 'phone' | 'select' | 'multiselect' | 'checkbox_group' | 'radio_group' | 'date' | 'checkbox' | 'image' | 'text_block'
  label: string
  label_en?: string
  required: boolean
  system: boolean
  options?: string[]
}


export interface RegistrationFormRead {
  id: string
  tenant_id: string
  event_id: string
  is_enabled: boolean
  barcode_generation_mode: 'immediate' | 'deferred'
  default_ticket_class: 'vip' | 'normal'
  default_template_id?: string
  success_message_ar?: string
  success_message_en?: string
  pending_approval_message_ar?: string
  pending_approval_message_en?: string
  fields: RegistrationFormField[]
  expires_at?: string | null
  created_at: string
  updated_at: string
}

export interface RegistrationFormCreate {
  is_enabled: boolean
  barcode_generation_mode: 'immediate' | 'deferred'
  default_ticket_class: 'vip' | 'normal'
  default_template_id?: string | null
  success_message_ar?: string | null
  success_message_en?: string | null
  pending_approval_message_ar?: string | null
  pending_approval_message_en?: string | null
  fields: RegistrationFormField[]
  expires_at?: string | null
}

export interface PublicRegistrationSubmit {
  registration_request_id: string
  guest_name: string
  guest_phone: string
  guest_email?: string
  custom_answers?: Record<string, any>
}

export const registrationApi = {
  /** Admin: Retrieve registration settings for an event */
  getRegistrationForm: (eventId: string) =>
    http.get<RegistrationFormRead>(`/events/${eventId}/registration-form`).then((r) => r.data),

  /** Admin: Save/update registration settings for an event */
  saveRegistrationForm: (eventId: string, data: RegistrationFormCreate) =>
    http.post<RegistrationFormRead>(`/events/${eventId}/registration-form`, data).then((r) => r.data),

  /** Public: Retrieve event and registration form fields for guest registration */
  getPublicRegisterInfo: (slug: string) =>
    http.get<{ event: any; form: any }>(`/public/events/${slug}/register-info`).then((r) => r.data),

  /** Public: Submit guest registration for an event */
  submitPublicRegistration: (slug: string, data: PublicRegistrationSubmit) =>
    http.post<{ status: string; message: string; mode: string; invitation?: any }>(`/public/events/${slug}/register`, data).then((r) => r.data),
}

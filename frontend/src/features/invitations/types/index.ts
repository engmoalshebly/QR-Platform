/* ── Invitation Types ── */

export type InvitationStatus =
  | "created"
  | "sent"
  | "viewed"
  | "accepted"
  | "declined"
  | "checked_in"
  | "revoked"
  | "expired";

export type TicketClass = "vip" | "normal";
export type DeliveryChannel = "sms" | "email" | "whatsapp" | "link" | "print";
export type RsvpStatus = "pending" | "accepted" | "declined" | "maybe";

export interface Invitation {
  id: string;
  tenant_id: string;
  event_id: string;
  template_id: string | null;
  guest_id: string | null;
  ticket_class: string;
  status: InvitationStatus;
  token: string;
  qr_data: string | null;
  guest_name: string | null;
  guest_count: number;
  guest_name_ar: string | null;
  guest_whatsapp?: string | null;
  guest_phone: string | null;
  guest_email: string | null;
  seat_number: string | null;
  table_number: string | null;
  gate_id: string | null;
  hall: string | null;
  zone: string | null;
  rsvp_status: RsvpStatus | null;
  rsvp_at: string | null;
  plus_one_count: number;
  rsvp_message: string | null;
  checked_in_at: string | null;
  checkin_count: number;
  barcode_svg_url: string | null;
  barcode_png_url: string | null;
  render_image_url: string | null;
  card_image_url: string | null;
  notes: string | null;
  metadata: Record<string, any> | null;
  is_registration: boolean;
  expires_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface InvitationCreateRequest {
  event_id: string;
  template_id?: string;
  guest_id?: string;
  ticket_class?: TicketClass;
  guest_name?: string;
  guest_count?: number;
  guest_name_ar?: string;
  guest_phone?: string;
  guest_email?: string;
  seat_number?: string;
  table_number?: string;
  gate_id?: string;
  hall?: string;
  zone?: string;
  notes?: string;
  metadata?: Record<string, any>;
  require_rsvp?: boolean;
}

export interface QuickInviteRequest {
  event_id: string;
  ticket_class?: TicketClass;
  template_id?: string;
  count?: number;
  names?: string[];
  gate_id?: string;
  require_rsvp?: boolean;
}

export interface BulkFromGuestsRequest {
  event_id: string;
  guest_ids: string[];
  ticket_class?: TicketClass;
  template_id?: string;
  gate_id?: string;
  require_rsvp?: boolean;
}

export interface InvitationUpdateRequest {
  guest_name?: string;
  guest_name_ar?: string;
  guest_phone?: string;
  guest_email?: string;
  seat_number?: string;
  table_number?: string;
  gate_id?: string;
  hall?: string;
  zone?: string;
  ticket_class?: TicketClass;
  notes?: string;
  status?: InvitationStatus;
  rsvp_status?: RsvpStatus | null;
  plus_one_count?: number;
  rsvp_message?: string | null;
  rsvp_at?: string | null;
  guest_count?: number;
  metadata?: Record<string, any>;
}

export interface InvitationSendRequest {
  client_request_id?: string; // Required by the server for WhatsApp; reuse on retries.
  allow_resend?: boolean;
  invitation_ids: string[];
  channel: DeliveryChannel;
  message?: string;
}

export interface InvitationListParams {
  event_id?: string;
  ticket_class?: TicketClass | "";
  status?: InvitationStatus | "";
  limit?: number;
  offset?: number;
}

export interface InvitationTableParams {
  event_id: string;
  tab: "rsvp" | "final";
  search?: string;
  ticket_class?: string;
  rsvp_status?: string;
  checkin?: string;
  whatsapp_state?: string;
  limit?: number;
  offset?: number;
}
export interface InvitationTablePage {
  items: Invitation[];
  total: number;
  limit: number;
  offset: number;
  stats: Record<string, number>;
  whatsapp: import("@features/whatsapp/api").DeliverySummary[] | null;
}

export const STATUS_LABELS: Record<InvitationStatus, string> = {
  created: "مُنشأة",
  sent: "مُرسلة",
  viewed: "مُشاهدة",
  accepted: "مقبولة",
  declined: "مرفوضة",
  checked_in: "حاضر",
  revoked: "ملغاة",
  expired: "منتهية",
};

export const STATUS_COLORS: Record<InvitationStatus, string> = {
  created: "#64748b",
  sent: "#3b82f6",
  viewed: "#8b5cf6",
  accepted: "#10b981",
  declined: "#ef4444",
  checked_in: "#059669",
  revoked: "#dc2626",
  expired: "#9ca3af",
};

export const CHANNEL_LABELS: Record<DeliveryChannel, string> = {
  link: "رابط مباشر",
  email: "بريد إلكتروني",
  sms: "رسالة نصية",
  whatsapp: "واتساب",
  print: "طباعة",
};

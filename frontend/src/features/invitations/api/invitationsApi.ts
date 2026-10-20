/**
 * invitationsApi.ts
 * Centralised API layer for the Invitations feature.
 */
import http from "@services/http/client";
import type {
  Invitation,
  InvitationCreateRequest,
  QuickInviteRequest,
  BulkFromGuestsRequest,
  InvitationUpdateRequest,
  InvitationSendRequest,
  InvitationListParams,
  InvitationTableParams,
  InvitationTablePage,
} from "../types";

/* ── Query Key Factory ── */
export const invitationKeys = {
  all: (tenantId: string) => ["invitations", tenantId] as const,
  list: (tenantId: string, params?: InvitationListParams) =>
    ["invitations", tenantId, "list", params] as const,
  detail: (tenantId: string, id: string) =>
    ["invitations", tenantId, "detail", id] as const,
};

/* ── API Functions ── */
export const invitationsAPI = {
  table: (params: InvitationTableParams, signal?: AbortSignal) =>
    http
      .get<InvitationTablePage>("/invitations/table", { params, signal })
      .then((r) => r.data),
  list: (params?: InvitationListParams) =>
    http.get<Invitation[]>("/invitations", { params }).then((r) => r.data),

  get: (id: string) =>
    http.get<Invitation>(`/invitations/${id}`).then((r) => r.data),

  create: (data: InvitationCreateRequest) =>
    http.post<Invitation>("/invitations", data).then((r) => r.data),

  quickCreate: (data: QuickInviteRequest) =>
    http
      .post<{ created: number; invitations: any[] }>("/invitations/quick", data)
      .then((r) => r.data),

  bulkFromGuests: (data: BulkFromGuestsRequest) =>
    http
      .post<{ created: number }>("/invitations/bulk-from-guests", data)
      .then((r) => r.data),

  update: (id: string, data: InvitationUpdateRequest) =>
    http.patch<Invitation>(`/invitations/${id}`, data).then((r) => r.data),

  revoke: (id: string) =>
    http.post(`/invitations/${id}/revoke`).then((r) => r.data),

  bulkRevoke: (ids: string[]) =>
    http
      .post<{ revoked: number }>("/invitations/bulk-revoke", null, {
        params: { invitation_ids: ids },
      })
      .then((r) => r.data),

  send: (data: InvitationSendRequest) =>
    http
      .post<{
        sent?: number;
        queued?: number;
        skipped?: number;
        failed?: number;
        request_id?: string;
      }>("/invitations/send", data)
      .then((r) => r.data),

  /** Public (no auth) */
  viewPublic: (token: string) =>
    http.get(`/invitations/view/${token}`).then((r) => r.data),

  rsvp: (
    token: string,
    data: { status: string; plus_one_count?: number; message?: string },
  ) => http.post(`/invitations/rsvp/${token}`, data).then((r) => r.data),
};

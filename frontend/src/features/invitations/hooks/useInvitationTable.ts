import { useEffect, useRef, useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { useAuthStore } from "@features/auth/store/authStore";
import { downloadAuthenticatedFile } from "@services/http/client";
import { invitationsAPI } from "../api/invitationsApi";
import type { InvitationTableParams } from "../types";

export const EMPTY_INVITATIONS: import("../types").Invitation[] = [];
const EMPTY_STATS = {
  total: 0,
  accepted: 0,
  declined: 0,
  pending: 0,
  plusOnes: 0,
  viewed: 0,
  sent: 0,
  unopened: 0,
  vip: 0,
  normal: 0,
  checkedIn: 0,
  remaining: 0,
};
export function useInvitationTable(
  filters: Omit<InvitationTableParams, "limit" | "offset">,
) {
  const tenantId = useAuthStore((s) => s.currentTenantId);
  const [search, setSearch] = useState(filters.search || "");
  useEffect(() => {
    const timer = window.setTimeout(() => setSearch(filters.search || ""), 300);
    return () => window.clearTimeout(timer);
  }, [filters.search]);
  const [limit, setLimit] = useState(50);
  const signature = JSON.stringify({ ...filters, search, tenantId, limit });
  const [position, setPosition] = useState({ signature, offset: 0 });
  const offset = position.signature === signature ? position.offset : 0;
  useEffect(() => {
    setPosition((previous) =>
      previous.signature === signature ? previous : { signature, offset: 0 },
    );
  }, [signature]);
  const params = { ...filters, search, limit, offset };
  const query = useQuery({
    queryKey: ["invitations", tenantId, "table", params],
    queryFn: ({ signal }) => invitationsAPI.table(params, signal),
    enabled: !!tenantId,
    retry: false,
    gcTime: 60000,
    refetchInterval: (q) =>
      Math.min(
        (q.state.data?.whatsapp?.some((d) =>
          ["queued", "waiting_connection", "sending"].includes(d.state),
        )
          ? 15000
          : 30000) *
          2 ** q.state.fetchFailureCount,
        120000,
      ),
  });
  // Preserve aggregate cards during a filter/page request, scoped to the same
  // tenant and event. Rows themselves are never carried across query scopes.
  const statsRef = useRef<{
    scope: string;
    stats: Record<string, number>;
  } | null>(null);
  const scope = `${tenantId}:${filters.event_id}:${filters.tab}`;
  useEffect(() => {
    if (query.data) statsRef.current = { scope, stats: query.data.stats };
  }, [query.data, scope]);
  const stats =
    query.data?.stats ||
    (statsRef.current?.scope === scope ? statsRef.current.stats : EMPTY_STATS);
  const exportRows = useMutation({
    mutationFn: async () => {
      const { limit: _limit, offset: _offset, ...allFilters } = params;
      const encoded = new URLSearchParams(
        Object.entries(allFilters)
          .filter(([, value]) => value !== undefined)
          .map(([key, value]) => [key, String(value)]),
      ).toString();
      await downloadAuthenticatedFile(
        new URL(
          `/api/v1/invitations/table/export?${encoded}`,
          window.location.origin,
        ).href,
        "تقرير_الدعوات.csv",
      );
    },
  });
  return {
    query,
    items: query.data?.items || EMPTY_INVITATIONS,
    stats,
    total: query.data?.total || 0,
    offset: query.data?.offset ?? offset,
    limit,
    setLimit,
    setOffset: (value: number) => setPosition({ signature, offset: value }),
    searching: (filters.search || "") !== search,
    signature,
    exportRows,
    params,
  };
}
export type InvitationTableController = ReturnType<typeof useInvitationTable>;

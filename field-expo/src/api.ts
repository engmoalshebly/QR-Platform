import type {
  DeviceSession,
  FieldCheckinResult,
  FieldEventBriefing,
  FieldEventCard,
  FieldMobileSettings,
  FieldSearchResult,
  FieldShift,
  LoginResponse,
  StoredAuth,
} from "./types";

const API_BASE = (process.env.EXPO_PUBLIC_API_URL ?? "").replace(/\/$/, "");

export class ApiError extends Error {
  constructor(
    message: string,
    public readonly status: number,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

function assertApiBase(): string {
  if (!API_BASE) {
    throw new ApiError("لم يتم ضبط رابط خادم Qentry. راجع ملف .env.", 0);
  }
  return API_BASE;
}

async function errorMessage(response: Response): Promise<string> {
  const body = (await response.json().catch(() => null)) as {
    detail?: string;
    message?: string;
  } | null;
  return body?.detail ?? body?.message ?? "تعذر تنفيذ الطلب. حاول مرة أخرى.";
}

async function request<T>(
  path: string,
  options: RequestInit = {},
  auth?: StoredAuth,
  fieldSession?: DeviceSession,
): Promise<T> {
  const headers = new Headers(options.headers);
  headers.set("Accept", "application/json");
  if (options.body) headers.set("Content-Type", "application/json");
  if (auth) {
    headers.set("Authorization", `Bearer ${auth.accessToken}`);
    headers.set("X-Tenant-ID", auth.tenant.tenant_id);
  }
  if (fieldSession) {
    headers.set("X-Field-Device-Session", fieldSession.id);
    headers.set("X-Field-Device-Token", fieldSession.session_token);
  }

  let response: Response;
  try {
    response = await fetch(`${assertApiBase()}${path}`, {
      ...options,
      headers,
    });
  } catch {
    throw new ApiError(
      "تعذر الاتصال بالخادم. تحقق من اتصال الشبكة وعنوان API.",
      0,
    );
  }
  if (!response.ok)
    throw new ApiError(await errorMessage(response), response.status);
  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}

export const fieldApi = {
  login(email: string, password: string, tenantId?: string) {
    return request<LoginResponse>("/auth/login", {
      method: "POST",
      body: JSON.stringify({ email, password, tenant_id: tenantId }),
    });
  },
  shifts(auth: StoredAuth, date: string) {
    return request<FieldShift[]>(
      `/mobile/shifts?date=${encodeURIComponent(date)}`,
      {},
      auth,
    );
  },
  events(auth: StoredAuth) {
    return request<FieldEventCard[]>("/mobile/events", {}, auth);
  },
  eventBriefing(auth: StoredAuth, eventId: string) {
    return request<FieldEventBriefing>(
      `/mobile/events/${eventId}/briefing`,
      {},
      auth,
    );
  },
  settings(auth: StoredAuth, deviceId: string) {
    return request<FieldMobileSettings>(
      `/mobile/settings?device_id=${encodeURIComponent(deviceId)}`,
      {},
      auth,
    );
  },
  startDeviceSession(
    auth: StoredAuth,
    body: {
      shift_id: string;
      device_id: string;
      device_name: string;
      platform: string;
      app_version: string;
    },
  ) {
    return request<DeviceSession>(
      "/mobile/device-sessions",
      {
        method: "POST",
        body: JSON.stringify(body),
      },
      auth,
    );
  },
  closeDeviceSession(auth: StoredAuth, session: DeviceSession) {
    return request<{ id: string; status: string }>(
      `/mobile/device-sessions/${session.id}/close`,
      {
        method: "POST",
      },
      auth,
    );
  },
  checkin(
    auth: StoredAuth,
    session: DeviceSession,
    body: {
      raw_code?: string;
      invitation_id?: string;
      entry_count: number;
      client_scan_id: string;
      client_captured_at: string;
      scan_method: "camera" | "manual" | "code128";
    },
  ) {
    return request<FieldCheckinResult>(
      "/mobile/checkins",
      {
        method: "POST",
        body: JSON.stringify(body),
      },
      auth,
      session,
    );
  },
  search(auth: StoredAuth, session: DeviceSession, query: string) {
    return request<FieldSearchResult[]>(
      `/mobile/invitations/search?query=${encodeURIComponent(query)}`,
      {},
      auth,
      session,
    );
  },
  requestAssistance(
    auth: StoredAuth,
    session: DeviceSession,
    assistanceType:
      | "duplicate"
      | "manual_confirmation"
      | "access"
      | "device"
      | "offline_conflict"
      | "other",
    note?: string,
  ) {
    return request<{ id: string; status: string; created_at: string }>(
      "/mobile/assistance",
      {
        method: "POST",
        body: JSON.stringify({ assistance_type: assistanceType, note }),
      },
      auth,
      session,
    );
  },
};

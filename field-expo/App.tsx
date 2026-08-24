import * as Haptics from "expo-haptics";
import { StatusBar } from "expo-status-bar";
import { useNetInfo } from "@react-native-community/netinfo";
import { useEffect, useMemo, useRef, useState } from "react";
import {
  ActivityIndicator,
  Alert,
  KeyboardAvoidingView,
  Pressable,
  RefreshControl,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  View,
} from "react-native";
import {
  SafeAreaProvider,
  useSafeAreaInsets,
} from "react-native-safe-area-context";

import { ApiError, fieldApi } from "./src/api";
import { AppButton } from "./src/components/app-button";
import { Scanner } from "./src/components/scanner";
import { StatusBanner } from "./src/components/status-banner";
import { deviceName, getFieldDeviceId, newClientScanId } from "./src/device";
import { secureStorage } from "./src/storage";
import type {
  FieldCheckinResult,
  FieldEventBriefing,
  FieldEventCard,
  FieldMobileSettings,
  FieldSearchResult,
  FieldShift,
  LoginResponse,
  StoredAuth,
  StoredFieldSession,
  TenantInfo,
} from "./src/types";

type Screen = "loading" | "login" | "tenant" | "events" | "briefing";
type EventTab = "overview" | "scan" | "settings";
type ScanMethod = "camera" | "code128" | "manual";

function formatDateTime(value: string, timezone?: string): string {
  return new Intl.DateTimeFormat("ar-SA", {
    weekday: "long",
    year: "numeric",
    month: "long",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
    timeZone: timezone,
  }).format(new Date(value));
}

function formatTime(value: string, timezone?: string): string {
  return new Intl.DateTimeFormat("ar-SA", {
    hour: "numeric",
    minute: "2-digit",
    timeZone: timezone,
  }).format(new Date(value));
}

function alertMessage(error: unknown): string {
  return error instanceof Error
    ? error.message
    : "حدث خطأ غير متوقع. حاول مرة أخرى.";
}

function resultTone(
  result: FieldCheckinResult,
): "success" | "warning" | "error" {
  if (result.result === "success") return "success";
  return result.requires_assistance ? "warning" : "error";
}

function resultTitle(result: FieldCheckinResult): string {
  const tone = resultTone(result);
  return tone === "success"
    ? "تم قبول الدخول"
    : tone === "warning"
      ? "تحتاج مراجعة مشرف"
      : "لم يُقبل الدخول";
}

function AppContent() {
  const insets = useSafeAreaInsets();
  const network = useNetInfo();
  const submitLock = useRef(false);
  const [screen, setScreen] = useState<Screen>("loading");
  const [auth, setAuth] = useState<StoredAuth | null>(null);
  const [pendingLogin, setPendingLogin] = useState<LoginResponse | null>(null);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [events, setEvents] = useState<FieldEventCard[]>([]);
  const [briefing, setBriefing] = useState<FieldEventBriefing | null>(null);
  const [fieldDeviceId, setFieldDeviceId] = useState<string | null>(null);
  const [fieldSettings, setFieldSettings] =
    useState<FieldMobileSettings | null>(null);
  const [settingsLoading, setSettingsLoading] = useState(false);
  const [eventTab, setEventTab] = useState<EventTab>("overview");
  const [fieldSession, setFieldSession] = useState<StoredFieldSession | null>(
    null,
  );
  const [result, setResult] = useState<FieldCheckinResult | null>(null);
  const [lastAcceptedCode, setLastAcceptedCode] = useState<{
    rawCode: string;
    method: "camera" | "code128";
  } | null>(null);
  const [additionalCount, setAdditionalCount] = useState(1);
  const [addingGuests, setAddingGuests] = useState(false);
  const [manualCode, setManualCode] = useState("");
  const [searchQuery, setSearchQuery] = useState("");
  const [searchResults, setSearchResults] = useState<FieldSearchResult[]>([]);
  const [searchSelection, setSearchSelection] =
    useState<FieldSearchResult | null>(null);
  const [searching, setSearching] = useState(false);

  const isOnline =
    network.isConnected !== false && network.isInternetReachable !== false;
  const activeEventId = fieldSession?.selectedShift.event_id ?? null;

  useEffect(() => {
    void (async () => {
      const [restoredAuth, restoredSession, storedDeviceId] = await Promise.all(
        [
          secureStorage.getAuth(),
          secureStorage.getFieldSession(),
          getFieldDeviceId(),
        ],
      );
      setFieldDeviceId(storedDeviceId);
      if (!restoredAuth) {
        setScreen("login");
        return;
      }
      setAuth(restoredAuth);
      if (restoredSession?.session.status === "active") {
        setEventTab("scan");
        try {
          const restoredBriefing = await fieldApi.eventBriefing(
            restoredAuth,
            restoredSession.selectedShift.event_id,
          );
          // Only enter the event screen after its protected briefing has
          // been restored.  A stale token must never leave the operator on a
          // route that has no data to render.
          setBriefing(restoredBriefing);
          setFieldSession(restoredSession);
          setScreen("briefing");
        } catch (cause) {
          await secureStorage.clearFieldSession();
          setFieldSession(null);
          setBriefing(null);

          if (cause instanceof ApiError && cause.status === 401) {
            await secureStorage.clearAuth();
            setAuth(null);
            setError(
              "انتهت جلسة الدخول. سجّل الدخول مرة أخرى لمتابعة وردياتك.",
            );
            setScreen("login");
            return;
          }

          setError(`تعذر استعادة جلسة البوابة: ${alertMessage(cause)}`);
          setScreen("events");
        }
      } else {
        setScreen("events");
      }
    })();
  }, []);

  useEffect(() => {
    if (screen === "events" && auth) void loadEvents(auth);
  }, [screen, auth]);

  async function loadEvents(currentAuth = auth) {
    if (!currentAuth) return;
    setBusy(true);
    setError(null);
    try {
      if (!isOnline)
        throw new ApiError("اتصل بالشبكة لتحميل حفلاتك المكلف بها.", 0);
      setEvents(await fieldApi.events(currentAuth));
    } catch (cause) {
      setError(alertMessage(cause));
    } finally {
      setBusy(false);
    }
  }

  async function loadBriefing(
    currentAuth: StoredAuth,
    eventId: string,
    showErrors = true,
  ) {
    try {
      if (!isOnline)
        throw new ApiError("يتطلب فتح ملف الحفل اتصالاً آمناً بالخادم.", 0);
      const next = await fieldApi.eventBriefing(currentAuth, eventId);
      setBriefing(next);
      return next;
    } catch (cause) {
      if (showErrors) {
        setError(alertMessage(cause));
        Alert.alert("تعذر فتح الحفل", alertMessage(cause));
      }
      return null;
    }
  }

  async function loadSettings(currentAuth = auth) {
    if (!currentAuth) return;
    setSettingsLoading(true);
    try {
      if (!isOnline) {
        throw new ApiError("تتطلب إعدادات الحساب اتصالاً آمناً بالخادم.", 0);
      }
      const deviceId = fieldDeviceId ?? (await getFieldDeviceId());
      setFieldDeviceId(deviceId);
      setFieldSettings(await fieldApi.settings(currentAuth, deviceId));
    } catch (cause) {
      Alert.alert("تعذر تحميل الإعدادات", alertMessage(cause));
    } finally {
      setSettingsLoading(false);
    }
  }

  useEffect(() => {
    if (screen === "briefing" && eventTab === "settings" && auth) {
      void loadSettings(auth);
    }
  }, [screen, eventTab, auth]);

  async function openEvent(event: FieldEventCard) {
    if (!auth || !event.is_available_today) return;
    setBusy(true);
    setError(null);
    const next = await loadBriefing(auth, event.event_id);
    setBusy(false);
    if (next) {
      setEventTab(activeEventId === event.event_id ? "scan" : "overview");
      setScreen("briefing");
    }
  }

  async function signIn() {
    if (!email.trim() || !password) {
      setError("أدخل البريد الإلكتروني وكلمة المرور.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const response = await fieldApi.login(email.trim(), password);
      const tenants = response.tenants ?? [];
      if (
        !response.access_token ||
        !response.refresh_token ||
        tenants.length === 0
      ) {
        throw new Error("تعذر إكمال تسجيل الدخول لهذا الحساب.");
      }
      if (response.requires_tenant_selection || tenants.length > 1) {
        setPendingLogin(response);
        setScreen("tenant");
      } else {
        await selectTenant(response, tenants[0]);
      }
    } catch (cause) {
      setError(alertMessage(cause));
    } finally {
      setBusy(false);
    }
  }

  async function selectTenant(response: LoginResponse, tenant: TenantInfo) {
    if (!response.access_token || !response.refresh_token) return;
    setBusy(true);
    setError(null);
    try {
      const selected = await fieldApi.login(
        email.trim(),
        password,
        tenant.tenant_id,
      );
      const finalAuth: StoredAuth = {
        accessToken: selected.access_token ?? response.access_token,
        refreshToken: selected.refresh_token ?? response.refresh_token,
        tenant,
      };
      await secureStorage.setAuth(finalAuth);
      setAuth(finalAuth);
      setPassword("");
      setPendingLogin(null);
      setScreen("events");
    } catch (cause) {
      setError(alertMessage(cause));
    } finally {
      setBusy(false);
    }
  }

  async function startShift(shift: FieldShift) {
    if (!auth) return false;
    if (
      fieldSession &&
      fieldSession.selectedShift.event_id !== shift.event_id
    ) {
      Alert.alert(
        "لديك جلسة بوابة مفتوحة",
        "أنه جلسة الحفل الحالي أولاً قبل فتح بوابة لحفل آخر.",
      );
      return false;
    }
    setBusy(true);
    setError(null);
    try {
      const session = await fieldApi.startDeviceSession(auth, {
        shift_id: shift.shift_id,
        device_id: fieldDeviceId ?? (await getFieldDeviceId()),
        device_name: deviceName(),
        platform: "native",
        app_version: "1.0.0",
      });
      const next = { session, selectedShift: shift };
      await secureStorage.setFieldSession(next);
      setFieldSession(next);
      setFieldDeviceId(session.device_id);
      setFieldSettings(null);
      setResult(null);
      setLastAcceptedCode(null);
      setEventTab("scan");
      return true;
    } catch (cause) {
      setError(alertMessage(cause));
      Alert.alert("تعذر تشغيل البوابة", alertMessage(cause));
      return false;
    } finally {
      setBusy(false);
    }
  }

  async function openScanner() {
    if (!briefing) return;
    if (activeEventId === briefing.event_id && fieldSession) {
      setEventTab("scan");
      return;
    }
    const available = briefing.shifts.filter((shift) => shift.can_start);
    if (available.length === 1) {
      await startShift(available[0]);
      return;
    }
    setEventTab("scan");
  }

  async function closeFieldSession() {
    if (!auth || !fieldSession) return;
    setBusy(true);
    try {
      await fieldApi.closeDeviceSession(auth, fieldSession.session);
      await secureStorage.clearFieldSession();
      setFieldSession(null);
      setResult(null);
      setLastAcceptedCode(null);
      setAddingGuests(false);
      setEventTab("overview");
      if (briefing) await loadBriefing(auth, briefing.event_id, false);
    } catch (cause) {
      Alert.alert("تعذر إنهاء الجلسة", alertMessage(cause));
    } finally {
      setBusy(false);
    }
  }

  async function submitCheckin(
    rawCode: string,
    method: ScanMethod,
    entryCount = 1,
  ) {
    if (!auth || !fieldSession || submitLock.current) return;
    if (!isOnline) {
      setResult({
        result: "offline",
        message:
          "لا توجد شبكة. لا تعتمد القراءة الآن إلا بعد تنزيل حزمة العمل المشفرة وتفعيل وضع عدم الاتصال.",
        invitation_id: null,
        guest_name: null,
        ticket_class: null,
        event_title: null,
        checkin_count: 0,
        guest_count: 0,
        remaining_count: 0,
        entry_count: entryCount,
        requires_assistance: true,
        code_format: null,
        idempotent: false,
      });
      return;
    }
    submitLock.current = true;
    setBusy(true);
    setSearchSelection(null);
    try {
      const response = await fieldApi.checkin(auth, fieldSession.session, {
        raw_code: rawCode,
        entry_count: entryCount,
        client_scan_id: newClientScanId(),
        client_captured_at: new Date().toISOString(),
        scan_method: method,
      });
      setResult(response);
      if (response.result === "success") {
        setLastAcceptedCode({
          rawCode,
          method: method === "manual" ? "camera" : method,
        });
        setAdditionalCount(1);
        setAddingGuests(false);
      }
      await Haptics.notificationAsync(
        response.result === "success"
          ? Haptics.NotificationFeedbackType.Success
          : Haptics.NotificationFeedbackType.Error,
      ).catch(() => undefined);
    } catch (cause) {
      setResult({
        result: "error",
        message: alertMessage(cause),
        invitation_id: null,
        guest_name: null,
        ticket_class: null,
        event_title: null,
        checkin_count: 0,
        guest_count: 0,
        remaining_count: 0,
        entry_count: entryCount,
        requires_assistance: true,
        code_format: null,
        idempotent: false,
      });
    } finally {
      submitLock.current = false;
      setBusy(false);
    }
  }

  async function submitManualInvitation(invitationId: string) {
    if (!auth || !fieldSession || submitLock.current) return;
    if (!isOnline) {
      Alert.alert(
        "البحث اليدوي يتطلب اتصالاً",
        "لا يمكن تأكيد دعوة عُثر عليها بالبحث اليدوي دون اتصال.",
      );
      return;
    }
    submitLock.current = true;
    setBusy(true);
    try {
      const response = await fieldApi.checkin(auth, fieldSession.session, {
        invitation_id: invitationId,
        entry_count: 1,
        client_scan_id: newClientScanId(),
        client_captured_at: new Date().toISOString(),
        scan_method: "manual",
      });
      setResult(response);
      setSearchSelection(null);
      await Haptics.notificationAsync(
        response.result === "success"
          ? Haptics.NotificationFeedbackType.Success
          : Haptics.NotificationFeedbackType.Error,
      ).catch(() => undefined);
    } catch (cause) {
      Alert.alert("تعذر التأكيد اليدوي", alertMessage(cause));
    } finally {
      submitLock.current = false;
      setBusy(false);
    }
  }

  async function searchManual() {
    if (!auth || !fieldSession || !searchQuery.trim()) return;
    setSearching(true);
    try {
      setSearchResults(
        await fieldApi.search(auth, fieldSession.session, searchQuery.trim()),
      );
    } catch (cause) {
      Alert.alert("تعذر البحث", alertMessage(cause));
    } finally {
      setSearching(false);
    }
  }

  async function callSupervisor() {
    if (!auth || !fieldSession) return;
    setBusy(true);
    try {
      await fieldApi.requestAssistance(
        auth,
        fieldSession.session,
        result?.result === "duplicate" ? "duplicate" : "manual_confirmation",
        result?.message,
      );
      Alert.alert(
        "تم الإرسال",
        "أرسل التطبيق طلب المساعدة إلى مشرف الوردية مع حالة البوابة فقط.",
      );
    } catch (cause) {
      Alert.alert("تعذر طلب المساعدة", alertMessage(cause));
    } finally {
      setBusy(false);
    }
  }

  async function signOut() {
    await secureStorage.clearFieldSession();
    await secureStorage.clearAuth();
    setAuth(null);
    setFieldSession(null);
    setBriefing(null);
    setEvents([]);
    setFieldSettings(null);
    setFieldDeviceId(null);
    setScreen("login");
  }

  const content = useMemo(() => {
    if (screen === "loading") {
      return (
        <View style={styles.center}>
          <ActivityIndicator size="large" color="#D7B46A" />
          <Text selectable style={styles.muted}>
            جاري تأمين جلسة الجهاز…
          </Text>
        </View>
      );
    }
    if (screen === "login") {
      return (
        <LoginScreen
          email={email}
          password={password}
          setEmail={setEmail}
          setPassword={setPassword}
          onSubmit={() => void signIn()}
          busy={busy}
          error={error}
        />
      );
    }
    if (screen === "tenant" && pendingLogin) {
      return (
        <TenantScreen
          tenants={pendingLogin.tenants ?? []}
          onSelect={(tenant) => void selectTenant(pendingLogin, tenant)}
          busy={busy}
          error={error}
        />
      );
    }
    if (screen === "events" && auth) {
      return (
        <EventsScreen
          auth={auth}
          events={events}
          busy={busy}
          error={error}
          onRefresh={() => void loadEvents()}
          onOpen={(event) => void openEvent(event)}
          onSignOut={() => void signOut()}
        />
      );
    }
    if (screen === "briefing" && auth && briefing) {
      return (
        <EventBriefingScreen
          auth={auth}
          briefing={briefing}
          tab={eventTab}
          fieldSession={
            activeEventId === briefing.event_id ? fieldSession : null
          }
          online={isOnline}
          busy={busy}
          result={result}
          addingGuests={addingGuests}
          additionalCount={additionalCount}
          setAdditionalCount={setAdditionalCount}
          onToggleAdditional={() => setAddingGuests((value) => !value)}
          onSubmitAdditional={() => {
            if (lastAcceptedCode)
              void submitCheckin(
                lastAcceptedCode.rawCode,
                lastAcceptedCode.method,
                additionalCount,
              );
          }}
          onOpenScan={() => void openScanner()}
          onSelectTab={setEventTab}
          onStartShift={(shift) => void startShift(shift)}
          onScan={(code, method) => submitCheckin(code, method, 1)}
          onManualCode={() =>
            manualCode.trim() &&
            void submitCheckin(manualCode.trim(), "manual", 1)
          }
          manualCode={manualCode}
          setManualCode={setManualCode}
          searchQuery={searchQuery}
          setSearchQuery={setSearchQuery}
          searchResults={searchResults}
          searchSelection={searchSelection}
          setSearchSelection={setSearchSelection}
          searching={searching}
          onSearch={() => void searchManual()}
          onManualInvitation={(id) => void submitManualInvitation(id)}
          onAssist={() => void callSupervisor()}
          settings={fieldSettings}
          settingsLoading={settingsLoading}
          onRefreshSettings={() => void loadSettings()}
          onSignOut={() => void signOut()}
          onClose={() => void closeFieldSession()}
          onBack={() => {
            setBriefing(null);
            setEventTab("overview");
            setScreen("events");
          }}
        />
      );
    }
    if (screen === "briefing" && auth && !briefing) {
      return (
        <BriefingRecoveryScreen
          message={error || "جارٍ استعادة ملف الحفل…"}
          onBack={() => {
            setBriefing(null);
            setFieldSession(null);
            setScreen("events");
          }}
        />
      );
    }
    return null;
  }, [
    screen,
    auth,
    pendingLogin,
    email,
    password,
    busy,
    error,
    events,
    briefing,
    eventTab,
    fieldDeviceId,
    fieldSettings,
    settingsLoading,
    fieldSession,
    activeEventId,
    isOnline,
    result,
    addingGuests,
    additionalCount,
    lastAcceptedCode,
    manualCode,
    searchQuery,
    searchResults,
    searchSelection,
    searching,
  ]);

  return (
    <View
      style={[
        styles.app,
        { paddingTop: insets.top, paddingBottom: insets.bottom },
      ]}
    >
      <StatusBar style="light" />
      {content}
    </View>
  );
}

function BriefingRecoveryScreen({
  message,
  onBack,
}: {
  message: string;
  onBack: () => void;
}) {
  return (
    <View style={styles.recoveryPage}>
      <View style={styles.recoveryCard}>
        <Text selectable style={styles.pageTitle}>
          تعذر فتح ملف الحفل
        </Text>
        <StatusBanner tone="error" message={message} />
        <Text selectable style={styles.helper}>
          لن يبدأ المسح أو تُعرض بيانات الدعوات قبل التأكد من جلسة آمنة وملف حفل
          صالح.
        </Text>
        <AppButton label="العودة إلى حفلاتي" onPress={onBack} tone="primary" />
      </View>
    </View>
  );
}

function LoginScreen({
  email,
  password,
  setEmail,
  setPassword,
  onSubmit,
  busy,
  error,
}: {
  email: string;
  password: string;
  setEmail: (value: string) => void;
  setPassword: (value: string) => void;
  onSubmit: () => void;
  busy: boolean;
  error: string | null;
}) {
  return (
    <KeyboardAvoidingView behavior="padding" style={styles.full}>
      <ScrollView
        contentContainerStyle={styles.authPage}
        keyboardShouldPersistTaps="handled"
      >
        <View style={styles.brand}>
          <Text selectable style={styles.eyebrow}>
            QENTRY FIELD
          </Text>
          <Text selectable style={styles.title}>
            تشغيل البوابات
          </Text>
          <Text selectable style={styles.subtle}>
            دخول آمن لمسّاحي الحضور فقط
          </Text>
        </View>
        <View style={styles.panel}>
          <Text selectable style={styles.panelTitle}>
            تسجيل الدخول
          </Text>
          <TextInput
            accessibilityLabel="البريد الإلكتروني"
            value={email}
            onChangeText={setEmail}
            autoCapitalize="none"
            autoCorrect={false}
            inputMode="email"
            placeholder="البريد الإلكتروني"
            placeholderTextColor="#7888A3"
            textAlign="right"
            style={styles.input}
          />
          <TextInput
            accessibilityLabel="كلمة المرور"
            value={password}
            onChangeText={setPassword}
            secureTextEntry
            placeholder="كلمة المرور"
            placeholderTextColor="#7888A3"
            textAlign="right"
            style={styles.input}
            onSubmitEditing={onSubmit}
          />
          <Text selectable style={styles.helper}>
            بعد الدخول تظهر فقط الحفلات والبوابات المسندة إليك؛ لا تمنح عضوية
            الحفل صلاحية المسح تلقائياً.
          </Text>
          {error && <StatusBanner message={error} tone="error" />}
          <AppButton
            label="الدخول إلى حفلاتي"
            onPress={onSubmit}
            loading={busy}
          />
        </View>
      </ScrollView>
    </KeyboardAvoidingView>
  );
}

function TenantScreen({
  tenants,
  onSelect,
  busy,
  error,
}: {
  tenants: TenantInfo[];
  onSelect: (tenant: TenantInfo) => void;
  busy: boolean;
  error: string | null;
}) {
  return (
    <ScrollView contentContainerStyle={styles.authPage}>
      <View style={styles.brand}>
        <Text selectable style={styles.eyebrow}>
          QENTRY FIELD
        </Text>
        <Text selectable style={styles.title}>
          اختر مساحة العمل
        </Text>
        <Text selectable style={styles.subtle}>
          سيتم تطبيق صلاحيات البوابات الخاصة بهذه المساحة.
        </Text>
      </View>
      <View style={styles.panel}>
        {error && <StatusBanner message={error} tone="error" />}
        {tenants.map((tenant) => (
          <Pressable
            key={tenant.tenant_id}
            disabled={busy}
            onPress={() => onSelect(tenant)}
            style={({ pressed }) => [
              styles.tenantCard,
              pressed && styles.pressed,
            ]}
          >
            <View>
              <Text selectable style={styles.tenantName}>
                {tenant.name}
              </Text>
              <Text selectable style={styles.muted}>
                {tenant.workspace_type === "institution"
                  ? "مؤسسة"
                  : "فريق تنظيم"}{" "}
                · {tenant.role}
              </Text>
            </View>
            <Text style={styles.chevron}>‹</Text>
          </Pressable>
        ))}
      </View>
    </ScrollView>
  );
}

function EventsScreen({
  auth,
  events,
  busy,
  error,
  onRefresh,
  onOpen,
  onSignOut,
}: {
  auth: StoredAuth;
  events: FieldEventCard[];
  busy: boolean;
  error: string | null;
  onRefresh: () => void;
  onOpen: (event: FieldEventCard) => void;
  onSignOut: () => void;
}) {
  return (
    <ScrollView
      contentInsetAdjustmentBehavior="automatic"
      refreshControl={
        <RefreshControl
          refreshing={busy}
          onRefresh={onRefresh}
          tintColor="#D7B46A"
        />
      }
      contentContainerStyle={styles.page}
    >
      <View style={styles.topRow}>
        <View>
          <Text selectable style={styles.eyebrow}>
            {auth.tenant.name}
          </Text>
          <Text selectable style={styles.pageTitle}>
            حفلاتي
          </Text>
          <Text selectable style={styles.subtle}>
            كل الحفلات المسندة إليك مع موعدها
          </Text>
        </View>
        <Pressable
          accessibilityRole="button"
          accessibilityLabel="تسجيل الخروج"
          onPress={onSignOut}
          style={styles.iconButton}
        >
          <Text style={styles.iconText}>↪</Text>
        </Pressable>
      </View>
      <StatusBanner message="يظهر كل حفل مسند إليك، لكن لا يمكنك فتح ملفه أو تشغيل البوابة إلا في يوم الحفل حسب منطق الخادم والمنطقة الزمنية." />
      <Text selectable style={styles.sectionHeading}>
        الحفلات المكلّف بها
      </Text>
      {error && <StatusBanner message={error} tone="error" />}
      {!busy && events.length === 0 ? (
        <View style={styles.empty}>
          <Text selectable style={styles.emptyTitle}>
            لا توجد حفلات مسندة إليك
          </Text>
          <Text selectable style={styles.muted}>
            اطلب من مدير الحفل إسنادك إلى وردية وبوابة محددة.
          </Text>
        </View>
      ) : (
        events.map((event) => (
          <View
            key={event.event_id}
            style={[
              styles.eventCard,
              event.is_available_today && styles.eventCardToday,
            ]}
          >
            <View style={styles.eventHeader}>
              <View
                style={[
                  styles.availabilityBadge,
                  event.is_available_today
                    ? styles.availableBadge
                    : styles.scheduledBadge,
                ]}
              >
                <Text selectable style={styles.availabilityText}>
                  {event.is_available_today ? "متاح اليوم" : "مجدول"}
                </Text>
              </View>
              <Text selectable style={styles.eventDate}>
                {formatDateTime(event.start_date, event.timezone)}
              </Text>
            </View>
            <Text selectable style={styles.eventTitle}>
              {event.title_ar || event.title}
            </Text>
            <Text selectable style={styles.eventVenue}>
              {event.venue_name_ar || event.venue_name || "لم يحدد الموقع بعد"}
            </Text>
            <View style={styles.eventMetaRow}>
              <Text selectable style={styles.muted}>
                {event.assigned_gate_count} بوابة مسندة
              </Text>
              <Text selectable style={styles.muted}>
                {event.assigned_shift_count} وردية
              </Text>
            </View>
            <AppButton
              label={
                event.has_active_device_session
                  ? "متابعة تشغيل الحفل"
                  : event.is_available_today
                    ? "فتح ملف الحفل"
                    : "يتاح في يوم الحفل"
              }
              onPress={() => onOpen(event)}
              disabled={!event.is_available_today || busy}
              loading={busy}
              tone={event.is_available_today ? "primary" : "secondary"}
            />
          </View>
        ))
      )}
    </ScrollView>
  );
}

function EventBriefingScreen({
  auth,
  briefing,
  tab,
  fieldSession,
  online,
  busy,
  result,
  addingGuests,
  additionalCount,
  setAdditionalCount,
  onToggleAdditional,
  onSubmitAdditional,
  onOpenScan,
  onSelectTab,
  onStartShift,
  onScan,
  onManualCode,
  manualCode,
  setManualCode,
  searchQuery,
  setSearchQuery,
  searchResults,
  searchSelection,
  setSearchSelection,
  searching,
  onSearch,
  onManualInvitation,
  onAssist,
  settings,
  settingsLoading,
  onRefreshSettings,
  onSignOut,
  onClose,
  onBack,
}: {
  auth: StoredAuth;
  briefing: FieldEventBriefing;
  tab: EventTab;
  fieldSession: StoredFieldSession | null;
  online: boolean;
  busy: boolean;
  result: FieldCheckinResult | null;
  addingGuests: boolean;
  additionalCount: number;
  setAdditionalCount: (value: number) => void;
  onToggleAdditional: () => void;
  onSubmitAdditional: () => void;
  onOpenScan: () => void;
  onSelectTab: (tab: EventTab) => void;
  onStartShift: (shift: FieldShift) => void;
  onScan: (code: string, method: "camera" | "code128") => Promise<void>;
  onManualCode: () => void;
  manualCode: string;
  setManualCode: (value: string) => void;
  searchQuery: string;
  setSearchQuery: (value: string) => void;
  searchResults: FieldSearchResult[];
  searchSelection: FieldSearchResult | null;
  setSearchSelection: (value: FieldSearchResult | null) => void;
  searching: boolean;
  onSearch: () => void;
  onManualInvitation: (id: string) => void;
  onAssist: () => void;
  settings: FieldMobileSettings | null;
  settingsLoading: boolean;
  onRefreshSettings: () => void;
  onSignOut: () => void;
  onClose: () => void;
  onBack: () => void;
}) {
  const activeShifts = briefing.shifts.filter((shift) => shift.can_start);
  const scanReady = Boolean(fieldSession);
  return (
    <View style={styles.full}>
      <ScrollView
        contentInsetAdjustmentBehavior="automatic"
        contentContainerStyle={styles.detailPage}
        keyboardShouldPersistTaps="handled"
      >
        <View style={styles.topRow}>
          <View>
            <Text selectable style={styles.eyebrow}>
              {auth.tenant.name}
            </Text>
            <Text selectable style={styles.pageTitle}>
              {briefing.title_ar || briefing.title}
            </Text>
            <Text selectable style={styles.subtle}>
              {formatDateTime(briefing.start_date, briefing.timezone)}
            </Text>
          </View>
          <Pressable
            accessibilityRole="button"
            accessibilityLabel="العودة إلى حفلاتي"
            onPress={onBack}
            style={styles.iconButton}
          >
            <Text style={styles.iconText}>›</Text>
          </Pressable>
        </View>
        {tab === "overview" && (
          <OverviewTab
            briefing={briefing}
            activeShifts={activeShifts}
            busy={busy}
            onStartShift={onStartShift}
          />
        )}
        {tab === "scan" && (
          <ScanTab
            briefing={briefing}
            scanReady={scanReady}
            fieldSession={fieldSession}
            online={online}
            busy={busy}
            result={result}
            addingGuests={addingGuests}
            additionalCount={additionalCount}
            setAdditionalCount={setAdditionalCount}
            onToggleAdditional={onToggleAdditional}
            onSubmitAdditional={onSubmitAdditional}
            onStartShift={onStartShift}
            activeShifts={activeShifts}
            onScan={onScan}
            onAssist={onAssist}
            manualCode={manualCode}
            setManualCode={setManualCode}
            onManualCode={onManualCode}
            searchQuery={searchQuery}
            setSearchQuery={setSearchQuery}
            searching={searching}
            onSearch={onSearch}
            searchResults={searchResults}
            searchSelection={searchSelection}
            setSearchSelection={setSearchSelection}
            onManualInvitation={onManualInvitation}
            onClose={onClose}
          />
        )}
        {tab === "settings" && (
          <SettingsTab
            settings={settings}
            loading={settingsLoading}
            onRefresh={onRefreshSettings}
            onSignOut={onSignOut}
          />
        )}
      </ScrollView>
      <BottomTabs
        tab={tab}
        scanReady={scanReady}
        onSelect={onSelectTab}
        onScan={onOpenScan}
      />
    </View>
  );
}

function OverviewTab({
  briefing,
  activeShifts,
  busy,
  onStartShift,
}: {
  briefing: FieldEventBriefing;
  activeShifts: FieldShift[];
  busy: boolean;
  onStartShift: (shift: FieldShift) => void;
}) {
  const stats = briefing.statistics;
  return (
    <>
      <View style={styles.eventInfo}>
        <Text selectable style={styles.eventInfoTitle}>
          ملف الحفل
        </Text>
        <Text selectable style={styles.eventInfoText}>
          {briefing.venue_name_ar ||
            briefing.venue_name ||
            "الموقع لم يحدد بعد"}
        </Text>
        <Text selectable style={styles.eventInfoText}>
          {briefing.description || "لا توجد ملاحظات تشغيلية إضافية."}
        </Text>
      </View>
      <View style={styles.statsGrid}>
        <StatCard
          label="إجمالي الدعوات"
          value={stats.total_invitations}
          accent="#D7B46A"
        />
        <StatCard
          label="دعوات VIP"
          value={stats.vip_invitations}
          accent="#B48CFF"
        />
        <StatCard
          label="دعوات عادية"
          value={stats.normal_invitations}
          accent="#61B7FF"
        />
        <StatCard
          label="الضيوف المتوقعون"
          value={stats.expected_guests}
          accent="#63D6A0"
        />
        <StatCard
          label="المسجلون الآن"
          value={stats.checked_in_guests}
          accent="#F6B26B"
        />
      </View>
      <View style={styles.panel}>
        <Text selectable style={styles.sectionTitle}>
          بواباتك ووردياتك
        </Text>
        {briefing.shifts.map((shift) => (
          <View key={shift.shift_id} style={styles.gateRow}>
            <View>
              <Text selectable style={styles.gateTitle}>
                {shift.gate_name_ar || shift.gate_name}
              </Text>
              <Text selectable style={styles.muted}>
                {formatTime(shift.starts_at, shift.timezone)} —{" "}
                {formatTime(shift.ends_at, shift.timezone)} ·{" "}
                {shift.shift_role === "supervisor" ? "مشرف" : "مسّاح"}
              </Text>
            </View>
            {shift.can_start ? (
              <AppButton
                label="تشغيل"
                onPress={() => onStartShift(shift)}
                disabled={busy}
                tone="primary"
                style={styles.inlineButton}
              />
            ) : (
              <Text selectable style={styles.notReady}>
                تفتح في وقت الوردية
              </Text>
            )}
          </View>
        ))}
      </View>
      {activeShifts.length === 0 && (
        <StatusBanner
          tone="warning"
          message="الحفل متاح اليوم، لكن قارئ الباركود لا يفتح إلا داخل وقت ورديتك الفعّال وعلى بوابة نشطة."
        />
      )}
    </>
  );
}

function ScanTab({
  briefing,
  scanReady,
  fieldSession,
  online,
  busy,
  result,
  addingGuests,
  additionalCount,
  setAdditionalCount,
  onToggleAdditional,
  onSubmitAdditional,
  onStartShift,
  activeShifts,
  onScan,
  onAssist,
  manualCode,
  setManualCode,
  onManualCode,
  searchQuery,
  setSearchQuery,
  searching,
  onSearch,
  searchResults,
  searchSelection,
  setSearchSelection,
  onManualInvitation,
  onClose,
}: {
  briefing: FieldEventBriefing;
  scanReady: boolean;
  fieldSession: StoredFieldSession | null;
  online: boolean;
  busy: boolean;
  result: FieldCheckinResult | null;
  addingGuests: boolean;
  additionalCount: number;
  setAdditionalCount: (value: number) => void;
  onToggleAdditional: () => void;
  onSubmitAdditional: () => void;
  onStartShift: (shift: FieldShift) => void;
  activeShifts: FieldShift[];
  onScan: (code: string, method: "camera" | "code128") => Promise<void>;
  onAssist: () => void;
  manualCode: string;
  setManualCode: (value: string) => void;
  onManualCode: () => void;
  searchQuery: string;
  setSearchQuery: (value: string) => void;
  searching: boolean;
  onSearch: () => void;
  searchResults: FieldSearchResult[];
  searchSelection: FieldSearchResult | null;
  setSearchSelection: (value: FieldSearchResult | null) => void;
  onManualInvitation: (id: string) => void;
  onClose: () => void;
}) {
  const maximumAdditional = Math.max(1, result?.remaining_count ?? 1);
  if (!scanReady)
    return (
      <View style={styles.scanStart}>
        <Text selectable style={styles.sectionTitle}>
          تشغيل قارئ الباركود
        </Text>
        <Text selectable style={styles.helper}>
          اختر البوابة المسندة إليك مرة واحدة. بعد بدء الجلسة تفتح الكاميرا
          فوراً في هذا التبويب.
        </Text>
        {activeShifts.length === 0 ? (
          <StatusBanner
            tone="warning"
            message="لا توجد وردية فعالة لك الآن. يظل الحفل معروضاً للمتابعة، لكن المسح مقفل حتى بداية ورديتك."
          />
        ) : (
          activeShifts.map((shift) => (
            <View key={shift.shift_id} style={styles.gateRow}>
              <View>
                <Text selectable style={styles.gateTitle}>
                  {shift.gate_name_ar || shift.gate_name}
                </Text>
                <Text selectable style={styles.muted}>
                  {formatTime(shift.starts_at, shift.timezone)} —{" "}
                  {formatTime(shift.ends_at, shift.timezone)}
                </Text>
              </View>
              <AppButton
                label="فتح الكاميرا"
                onPress={() => onStartShift(shift)}
                disabled={busy}
                loading={busy}
                style={styles.inlineButton}
              />
            </View>
          ))
        )}
      </View>
    );
  return (
    <>
      <View
        style={[
          styles.connection,
          online ? styles.connectionOnline : styles.connectionOffline,
        ]}
      >
        <Text selectable style={styles.connectionText}>
          {online
            ? `متصل · ${fieldSession?.selectedShift.gate_name_ar || fieldSession?.selectedShift.gate_name}`
            : "غير متصل — لا تقبل قراءة غير محفوظة"}
        </Text>
      </View>
      {result && (
        <ScanResult
          result={result}
          addingGuests={addingGuests}
          additionalCount={additionalCount}
          setAdditionalCount={setAdditionalCount}
          maxAdditional={maximumAdditional}
          onToggleAdditional={onToggleAdditional}
          onSubmitAdditional={onSubmitAdditional}
          onAssist={onAssist}
          busy={busy}
        />
      )}
      {!addingGuests && <Scanner onScan={onScan} />}
      {addingGuests && (
        <View style={styles.countPanel}>
          <Text selectable style={styles.panelTitle}>
            إدخال مرافقين للدعوة نفسها
          </Text>
          <Text selectable style={styles.helper}>
            هذه الخطوة تظهر فقط للدعوات الجماعية. الحد المتبقي:{" "}
            {maximumAdditional}
          </Text>
          <View style={styles.counter}>
            <Pressable
              onPress={() =>
                setAdditionalCount(Math.max(1, additionalCount - 1))
              }
              style={styles.counterButton}
            >
              <Text style={styles.counterText}>−</Text>
            </Pressable>
            <Text selectable style={styles.countText}>
              {additionalCount}
            </Text>
            <Pressable
              onPress={() =>
                setAdditionalCount(
                  Math.min(maximumAdditional, additionalCount + 1),
                )
              }
              style={styles.counterButton}
            >
              <Text style={styles.counterText}>+</Text>
            </Pressable>
          </View>
          <AppButton
            label="تأكيد الداخلين"
            onPress={onSubmitAdditional}
            loading={busy}
            tone="success"
          />
          <AppButton
            label="إلغاء"
            onPress={onToggleAdditional}
            tone="secondary"
          />
        </View>
      )}
      {!addingGuests && (
        <ScanTools
          scanReady={scanReady}
          busy={busy}
          manualCode={manualCode}
          setManualCode={setManualCode}
          onManualCode={onManualCode}
          searchQuery={searchQuery}
          setSearchQuery={setSearchQuery}
          searching={searching}
          onSearch={onSearch}
          searchResults={searchResults}
          searchSelection={searchSelection}
          setSearchSelection={setSearchSelection}
          onManualInvitation={onManualInvitation}
          onAssist={onAssist}
        />
      )}
      <Pressable onPress={onClose} disabled={busy} style={styles.closeSession}>
        <Text selectable style={styles.closeSessionText}>
          إنهاء وتسليم جلسة الجهاز
        </Text>
      </Pressable>
    </>
  );
}

function ScanResult({
  result,
  addingGuests,
  additionalCount: _additionalCount,
  setAdditionalCount: _setAdditionalCount,
  maxAdditional,
  onToggleAdditional,
  onSubmitAdditional: _onSubmitAdditional,
  onAssist,
  busy,
}: {
  result: FieldCheckinResult;
  addingGuests: boolean;
  additionalCount: number;
  setAdditionalCount: (value: number) => void;
  maxAdditional: number;
  onToggleAdditional: () => void;
  onSubmitAdditional: () => void;
  onAssist: () => void;
  busy: boolean;
}) {
  const tone = resultTone(result);
  return (
    <View
      accessibilityRole="alert"
      style={[styles.resultCard, resultToneStyles[tone]]}
    >
      <Text selectable style={styles.resultMark}>
        {tone === "success" ? "✓" : tone === "warning" ? "!" : "×"}
      </Text>
      <Text selectable style={styles.resultTitle}>
        {resultTitle(result)}
      </Text>
      <Text selectable style={styles.resultMessage}>
        {result.message}
      </Text>
      {result.guest_name && (
        <Text selectable style={styles.resultGuest}>
          {result.guest_name}
        </Text>
      )}
      <Text selectable style={styles.resultMeta}>
        {result.ticket_class ? `فئة الدعوة: ${result.ticket_class}` : ""}
        {result.remaining_count > 0
          ? ` · المتبقي: ${result.remaining_count}`
          : ""}
      </Text>
      {result.result === "success" &&
      result.remaining_count > 0 &&
      !addingGuests ? (
        <AppButton
          label={`إدخال مرافقين (${maxAdditional} متبقٍ)`}
          onPress={onToggleAdditional}
          disabled={busy}
          tone="secondary"
        />
      ) : null}
      {result.requires_assistance ? (
        <AppButton
          label="استدعاء مشرف الوردية"
          onPress={onAssist}
          loading={busy}
          tone="secondary"
        />
      ) : null}
    </View>
  );
}

function ScanTools({
  scanReady,
  busy,
  manualCode,
  setManualCode,
  onManualCode,
  searchQuery,
  setSearchQuery,
  searching,
  onSearch,
  searchResults,
  searchSelection,
  setSearchSelection,
  onManualInvitation,
  onAssist,
}: {
  scanReady: boolean;
  busy: boolean;
  manualCode: string;
  setManualCode: (value: string) => void;
  onManualCode: () => void;
  searchQuery: string;
  setSearchQuery: (value: string) => void;
  searching: boolean;
  onSearch: () => void;
  searchResults: FieldSearchResult[];
  searchSelection: FieldSearchResult | null;
  setSearchSelection: (value: FieldSearchResult | null) => void;
  onManualInvitation: (id: string) => void;
  onAssist: () => void;
}) {
  if (!scanReady)
    return (
      <View style={styles.scanStart}>
        <Text selectable style={styles.sectionTitle}>
          المساعدة والإدخال اليدوي
        </Text>
        <StatusBanner
          tone="warning"
          message="ابدأ جلسة بوابة فعالة أولاً قبل استخدام البحث أو الإدخال اليدوي."
        />
      </View>
    );
  return (
    <>
      <View style={styles.manualPanel}>
        <Text selectable style={styles.sectionTitle}>
          إدخال رمز يدوي
        </Text>
        <Text selectable style={styles.helper}>
          استخدمه عند تعذر قراءة الكاميرا فقط. التحقق يتم في الخادم ضمن بوابتك
          الحالية.
        </Text>
        <TextInput
          value={manualCode}
          onChangeText={setManualCode}
          placeholder="رمز الدعوة أو رابطها"
          placeholderTextColor="#7888A3"
          textAlign="right"
          style={styles.input}
        />
        <AppButton
          label="تحقق من الرمز"
          onPress={onManualCode}
          disabled={!manualCode.trim() || busy}
          loading={busy}
          tone="secondary"
        />
      </View>
      <View style={styles.manualPanel}>
        <Text selectable style={styles.sectionTitle}>
          بحث يدوي محدود
        </Text>
        <Text selectable style={styles.helper}>
          نتائج محدودة للحفل والبوابة الحاليين فقط؛ لا توجد قائمة ضيوف قابلة
          للتصفح.
        </Text>
        <View style={styles.searchRow}>
          <TextInput
            value={searchQuery}
            onChangeText={setSearchQuery}
            placeholder="الاسم أو رقم المقعد أو الطاولة"
            placeholderTextColor="#7888A3"
            textAlign="right"
            style={[styles.input, styles.searchInput]}
            onSubmitEditing={onSearch}
          />
          <Pressable
            accessibilityRole="button"
            onPress={onSearch}
            style={styles.searchButton}
          >
            <Text style={styles.searchButtonText}>
              {searching ? "…" : "بحث"}
            </Text>
          </Pressable>
        </View>
        {searchResults.map((item) => (
          <Pressable
            key={item.id}
            onPress={() => setSearchSelection(item)}
            style={[
              styles.searchResult,
              searchSelection?.id === item.id && styles.selectedSearchResult,
            ]}
          >
            <View>
              <Text selectable style={styles.searchResultName}>
                {item.label}
              </Text>
              <Text selectable style={styles.muted}>
                {item.ticket_class} · المتبقي {item.remaining_count}
              </Text>
            </View>
            <Text selectable style={styles.countBadge}>
              {item.guest_count}
            </Text>
          </Pressable>
        ))}
        {searchSelection && (
          <AppButton
            label="تأكيد دخول الدعوة المختارة"
            onPress={() => onManualInvitation(searchSelection.id)}
            loading={busy}
            tone="success"
          />
        )}
      </View>
      <View style={styles.manualPanel}>
        <Text selectable style={styles.sectionTitle}>
          طلب مساعدة
        </Text>
        <Text selectable style={styles.helper}>
          استخدمه للرمز المتعارض أو الاستثناء. لا يستطيع المسّاح تجاوز رفض
          الدعوة بنفسه.
        </Text>
        <AppButton
          label="استدعاء مشرف الوردية"
          onPress={onAssist}
          loading={busy}
          tone="secondary"
        />
      </View>
    </>
  );
}

const fieldPermissionLabels: Record<string, string> = {
  "checkin.scan": "مسح الباركود",
  "checkin.search": "بحث يدوي محدود",
  "checkin.manual": "تأكيد يدوي للدعوات",
  "checkin.supervise": "إشراف البوابة",
  "gates.view": "عرض البوابات",
  "gate.shift.manage": "إدارة الورديات",
};

function SettingsTab({
  settings,
  loading,
  onRefresh,
  onSignOut,
}: {
  settings: FieldMobileSettings | null;
  loading: boolean;
  onRefresh: () => void;
  onSignOut: () => void;
}) {
  if (!settings) {
    return (
      <View style={styles.settingsEmpty}>
        {loading ? (
          <ActivityIndicator size="large" color="#D7B46A" />
        ) : (
          <Text selectable style={styles.helper}>
            لم تُحمّل إعدادات الحساب بعد.
          </Text>
        )}
        <AppButton
          label="تحديث الإعدادات"
          onPress={onRefresh}
          loading={loading}
          tone="secondary"
        />
      </View>
    );
  }

  const displayName =
    settings.user.full_name || settings.user.email || "عضو التشغيل";
  const session = settings.device.active_session;
  return (
    <>
      <View style={styles.settingsProfile}>
        <View style={styles.avatarCircle}>
          <Text selectable style={styles.avatarText}>
            {displayName.trim().slice(0, 1).toUpperCase()}
          </Text>
        </View>
        <View style={styles.settingsProfileText}>
          <Text selectable style={styles.panelTitle}>
            {displayName}
          </Text>
          <Text selectable style={styles.muted}>
            حساب تشغيل شخصي
          </Text>
        </View>
        <View style={styles.verifiedBadge}>
          <Text selectable style={styles.verifiedBadgeText}>
            {settings.user.email_verified ? "موثّق" : "غير موثّق"}
          </Text>
        </View>
      </View>

      <View style={styles.settingsCard}>
        <Text selectable style={styles.sectionTitle}>
          بيانات المستخدم
        </Text>
        <SettingsRow
          label="الاسم"
          value={settings.user.full_name || "غير مضاف"}
        />
        <SettingsRow
          label="البريد الإلكتروني"
          value={settings.user.email || "غير متوفر"}
        />
        <SettingsRow
          label="رقم الجوال"
          value={settings.user.phone || "غير مضاف"}
        />
        <SettingsRow
          label="حالة الحساب"
          value={
            settings.user.status === "active"
              ? "نشط"
              : settings.user.status || "غير معروفة"
          }
        />
        <SettingsRow label="معرّف الحساب" value={settings.user.id} compact />
      </View>

      <View style={styles.settingsCard}>
        <Text selectable style={styles.sectionTitle}>
          مساحة العمل
        </Text>
        <SettingsRow label="المساحة" value={settings.workspace.name} />
        <SettingsRow
          label="النوع"
          value={
            settings.workspace.workspace_type === "organizer"
              ? "فريق تنظيم"
              : "مؤسسة"
          }
        />
        <SettingsRow
          label="دور العضوية"
          value={settings.workspace.membership_role}
        />
        <SettingsRow
          label="الباقة"
          value={settings.workspace.plan || "غير محددة"}
        />
        <SettingsRow
          label="حالة العضوية"
          value={
            settings.workspace.membership_status === "active"
              ? "نشطة"
              : settings.workspace.membership_status
          }
        />
      </View>

      <View style={styles.settingsCard}>
        <Text selectable style={styles.sectionTitle}>
          الجهاز وجلسة البوابة
        </Text>
        <SettingsRow
          label="معرّف هذا الجهاز"
          value={settings.device.device_id || "لم يُسجّل بعد"}
          compact
        />
        {session ? (
          <>
            <SettingsRow label="الجلسة" value="نشطة" tone="success" />
            <SettingsRow
              label="الحفل"
              value={session.event_title_ar || session.event_title}
            />
            <SettingsRow
              label="البوابة"
              value={session.gate_name_ar || session.gate_name}
            />
            <SettingsRow
              label="بدء الجلسة"
              value={formatDateTime(session.started_at)}
            />
          </>
        ) : (
          <Text selectable style={styles.helper}>
            لا توجد جلسة بوابة نشطة على هذا الجهاز.
          </Text>
        )}
      </View>

      <View style={styles.settingsCard}>
        <Text selectable style={styles.sectionTitle}>
          صلاحيات التشغيل الفعلية
        </Text>
        <Text selectable style={styles.helper}>
          تُطبّق هذه الصلاحيات من الخادم في كل طلب، ولا يكفي إظهار التبويب لمنح
          الوصول.
        </Text>
        <View style={styles.permissionList}>
          {settings.permissions.length ? (
            settings.permissions.map((permission) => (
              <View key={permission} style={styles.permissionChip}>
                <Text selectable style={styles.permissionChipText}>
                  {fieldPermissionLabels[permission] || permission}
                </Text>
              </View>
            ))
          ) : (
            <Text selectable style={styles.notReady}>
              لا توجد صلاحيات تشغيلية مفعّلة.
            </Text>
          )}
        </View>
      </View>

      <AppButton
        label="تحديث البيانات والصلاحيات"
        onPress={onRefresh}
        loading={loading}
        tone="secondary"
      />
      <AppButton
        label="تسجيل الخروج من هذا الجهاز"
        onPress={onSignOut}
        tone="danger"
      />
    </>
  );
}

function SettingsRow({
  label,
  value,
  compact = false,
  tone,
}: {
  label: string;
  value: string;
  compact?: boolean;
  tone?: "success";
}) {
  return (
    <View style={styles.settingsRow}>
      <Text selectable style={styles.settingsLabel}>
        {label}
      </Text>
      <Text
        selectable
        style={[
          styles.settingsValue,
          compact && styles.settingsValueCompact,
          tone === "success" && styles.settingsValueSuccess,
        ]}
      >
        {value}
      </Text>
    </View>
  );
}

function BottomTabs({
  tab,
  scanReady,
  onSelect,
  onScan,
}: {
  tab: EventTab;
  scanReady: boolean;
  onSelect: (tab: EventTab) => void;
  onScan: () => void;
}) {
  return (
    <View style={styles.bottomTabs}>
      <Pressable
        accessibilityRole="tab"
        accessibilityState={{ selected: tab === "overview" }}
        onPress={() => onSelect("overview")}
        style={[styles.tabButton, tab === "overview" && styles.tabButtonActive]}
      >
        <Text style={styles.tabIcon}>▦</Text>
        <Text
          style={[styles.tabLabel, tab === "overview" && styles.tabLabelActive]}
        >
          الملخص
        </Text>
      </Pressable>
      <Pressable
        accessibilityRole="tab"
        accessibilityState={{ selected: tab === "scan" }}
        onPress={onScan}
        style={[styles.scanTab, tab === "scan" && styles.scanTabActive]}
      >
        <Text style={styles.scanTabIcon}>{scanReady ? "▣" : "⌁"}</Text>
        <Text style={styles.scanTabLabel}>مسح</Text>
      </Pressable>
      <Pressable
        accessibilityRole="tab"
        accessibilityState={{ selected: tab === "settings" }}
        onPress={() => onSelect("settings")}
        style={[styles.tabButton, tab === "settings" && styles.tabButtonActive]}
      >
        <Text style={styles.tabIcon}>⚙</Text>
        <Text
          style={[styles.tabLabel, tab === "settings" && styles.tabLabelActive]}
        >
          الإعدادات
        </Text>
      </Pressable>
    </View>
  );
}

function StatCard({
  label,
  value,
  accent,
}: {
  label: string;
  value: number;
  accent: string;
}) {
  return (
    <View style={[styles.statCard, { borderTopColor: accent }]}>
      <Text selectable style={styles.statValue}>
        {value}
      </Text>
      <Text selectable style={styles.statLabel}>
        {label}
      </Text>
    </View>
  );
}

export default function App() {
  return (
    <SafeAreaProvider>
      <AppContent />
    </SafeAreaProvider>
  );
}

const styles = StyleSheet.create({
  // @ts-ignore This declaration is split across a legacy single-line style map; a later key supersedes the earlier pressed style.
  app: { flex: 1, backgroundColor: "#091321", direction: "rtl" },
  full: { flex: 1 },
  center: { flex: 1, alignItems: "center", justifyContent: "center", gap: 14 },
  recoveryPage: {
    flex: 1,
    justifyContent: "center",
    paddingHorizontal: 18,
  },
  recoveryCard: {
    backgroundColor: "#132237",
    borderRadius: 24,
    padding: 22,
    gap: 16,
    borderWidth: 1,
    borderColor: "#8A3849",
    borderCurve: "continuous",
  },
  authPage: { flexGrow: 1, padding: 24, justifyContent: "center", gap: 24 },
  page: { paddingHorizontal: 18, paddingBottom: 32, gap: 16 },
  detailPage: { paddingHorizontal: 18, paddingBottom: 104, gap: 16 },
  brand: { gap: 7, alignItems: "flex-end" },
  eyebrow: {
    color: "#D7B46A",
    fontSize: 12,
    fontWeight: "900",
    letterSpacing: 1.2,
    textAlign: "right",
  },
  title: {
    color: "#F8FAFC",
    fontSize: 33,
    fontWeight: "900",
    textAlign: "right",
  },
  pageTitle: {
    color: "#F8FAFC",
    fontSize: 25,
    fontWeight: "900",
    textAlign: "right",
  },
  subtle: { color: "#A9B7CE", fontSize: 15, textAlign: "right" },
  panel: {
    backgroundColor: "#132237",
    borderRadius: 24,
    padding: 20,
    gap: 14,
    borderWidth: 1,
    borderColor: "#2C405D",
    borderCurve: "continuous",
  },
  panelTitle: {
    color: "#F8FAFC",
    fontSize: 20,
    fontWeight: "900",
    textAlign: "right",
  },
  input: {
    minHeight: 54,
    borderRadius: 14,
    borderWidth: 1,
    borderColor: "#3A4E6D",
    backgroundColor: "#0D182A",
    color: "#F8FAFC",
    paddingHorizontal: 14,
    fontSize: 16,
    borderCurve: "continuous",
  },
  helper: {
    color: "#9CB0CD",
    fontSize: 14,
    lineHeight: 21,
    textAlign: "right",
  },
  muted: { color: "#9CB0CD", fontSize: 13, textAlign: "right" },
  topRow: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "flex-start",
    paddingTop: 10,
  },
  iconButton: {
    height: 42,
    width: 42,
    borderRadius: 14,
    justifyContent: "center",
    alignItems: "center",
    backgroundColor: "#15243A",
    borderWidth: 1,
    borderColor: "#314563",
  },
  iconText: { color: "#D7B46A", fontSize: 26, fontWeight: "700" },
  tenantCard: {
    backgroundColor: "#0D182A",
    borderWidth: 1,
    borderColor: "#354C6E",
    padding: 16,
    borderRadius: 16,
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "center",
    borderCurve: "continuous",
  },
  tenantName: {
    color: "#F8FAFC",
    fontSize: 17,
    fontWeight: "800",
    textAlign: "right",
  },
  chevron: { color: "#D7B46A", fontSize: 28 },
  pressed: { opacity: 0.8, transform: [{ scale: 0.985 }] },
  sectionHeading: {
    color: "#F8FAFC",
    fontSize: 18,
    fontWeight: "900",
    textAlign: "right",
  },
  empty: {
    padding: 28,
    borderRadius: 22,
    alignItems: "center",
    gap: 8,
    backgroundColor: "#132237",
    borderWidth: 1,
    borderColor: "#2C405D",
    borderCurve: "continuous",
  },
  emptyTitle: {
    color: "#F8FAFC",
    fontSize: 18,
    fontWeight: "900",
    textAlign: "center",
  },
  eventCard: {
    backgroundColor: "#132237",
    borderRadius: 22,
    padding: 18,
    gap: 10,
    borderWidth: 1,
    borderColor: "#2C405D",
    borderCurve: "continuous",
  },
  eventCardToday: { borderColor: "#A77B2F", backgroundColor: "#17263C" },
  eventHeader: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "center",
    gap: 8,
  },
  availabilityBadge: {
    borderRadius: 999,
    paddingVertical: 6,
    paddingHorizontal: 10,
  },
  availableBadge: { backgroundColor: "#144C39" },
  scheduledBadge: { backgroundColor: "#24334A" },
  availabilityText: { color: "#F8FAFC", fontSize: 12, fontWeight: "900" },
  eventDate: {
    color: "#D7B46A",
    fontSize: 13,
    fontWeight: "800",
    flex: 1,
    textAlign: "right",
  },
  eventTitle: {
    color: "#F8FAFC",
    fontSize: 21,
    fontWeight: "900",
    textAlign: "right",
  },
  eventVenue: { color: "#C9D7EC", fontSize: 15, textAlign: "right" },
  eventMetaRow: {
    flexDirection: "row",
    justifyContent: "space-between",
    borderTopWidth: 1,
    borderTopColor: "#293C58",
    paddingTop: 10,
  },
  eventInfo: {
    backgroundColor: "#132237",
    borderWidth: 1,
    borderColor: "#2C405D",
    padding: 18,
    borderRadius: 22,
    gap: 6,
    borderCurve: "continuous",
  },
  eventInfoTitle: {
    color: "#D7B46A",
    fontSize: 13,
    fontWeight: "900",
    textAlign: "right",
  },
  eventInfoText: {
    color: "#F1F5FA",
    fontSize: 15,
    lineHeight: 23,
    textAlign: "right",
  },
  statsGrid: { flexDirection: "row", flexWrap: "wrap", gap: 10 },
  statCard: {
    width: "31%",
    minWidth: 100,
    flexGrow: 1,
    backgroundColor: "#132237",
    borderWidth: 1,
    borderColor: "#2C405D",
    borderTopWidth: 3,
    borderRadius: 16,
    padding: 14,
    gap: 4,
    borderCurve: "continuous",
  },
  statValue: {
    color: "#F8FAFC",
    fontSize: 25,
    fontWeight: "900",
    textAlign: "right",
    fontVariant: ["tabular-nums"],
  },
  statLabel: {
    color: "#9CB0CD",
    fontSize: 12,
    lineHeight: 18,
    textAlign: "right",
  },
  sectionTitle: {
    color: "#F8FAFC",
    fontSize: 18,
    fontWeight: "900",
    textAlign: "right",
  },
  gateRow: {
    minHeight: 70,
    borderTopWidth: 1,
    borderTopColor: "#2C405D",
    paddingTop: 12,
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "center",
    gap: 8,
  },
  gateTitle: {
    color: "#F8FAFC",
    fontSize: 16,
    fontWeight: "800",
    textAlign: "right",
  },
  notReady: {
    color: "#D7B46A",
    fontSize: 12,
    fontWeight: "800",
    textAlign: "center",
  },
  inlineButton: { minHeight: 40, borderRadius: 12, paddingHorizontal: 12 },
  scanStart: {
    backgroundColor: "#132237",
    borderRadius: 22,
    padding: 20,
    gap: 14,
    borderWidth: 1,
    borderColor: "#2C405D",
    borderCurve: "continuous",
  },
  connection: {
    borderRadius: 14,
    padding: 12,
    borderWidth: 1,
    borderCurve: "continuous",
  },
  connectionOnline: { backgroundColor: "#16382F", borderColor: "#247453" },
  connectionOffline: { backgroundColor: "#3B311D", borderColor: "#8F7130" },
  connectionText: {
    color: "#E9EEF8",
    textAlign: "right",
    fontWeight: "800",
    fontSize: 13,
  },
  resultCard: {
    borderRadius: 24,
    padding: 20,
    alignItems: "center",
    gap: 8,
    borderWidth: 2,
    borderCurve: "continuous",
  },
  resultMark: { fontSize: 42, fontWeight: "900", color: "#FFF" },
  resultTitle: { color: "#FFF", fontSize: 25, fontWeight: "900" },
  resultMessage: {
    color: "#F5F7FB",
    textAlign: "center",
    fontSize: 16,
    lineHeight: 24,
  },
  resultGuest: { color: "#FFFFFF", fontSize: 19, fontWeight: "900" },
  resultMeta: { color: "#DCE7F8", textAlign: "center", fontSize: 14 },
  countPanel: {
    backgroundColor: "#132237",
    borderWidth: 1,
    borderColor: "#D7B46A",
    borderRadius: 24,
    padding: 20,
    gap: 14,
    borderCurve: "continuous",
  },
  counter: {
    flexDirection: "row",
    justifyContent: "center",
    alignItems: "center",
    gap: 24,
  },
  counterButton: {
    width: 54,
    height: 54,
    borderRadius: 16,
    justifyContent: "center",
    alignItems: "center",
    backgroundColor: "#223756",
    borderWidth: 1,
    borderColor: "#405879",
  },
  counterText: { color: "#F8FAFC", fontSize: 31, fontWeight: "600" },
  countText: {
    color: "#F8FAFC",
    fontSize: 34,
    fontWeight: "900",
    minWidth: 46,
    textAlign: "center",
    fontVariant: ["tabular-nums"],
  },
  closeSession: { alignItems: "center", padding: 14 },
  closeSessionText: { color: "#FCA5A5", fontSize: 15, fontWeight: "800" },
  manualPanel: {
    backgroundColor: "#132237",
    borderRadius: 22,
    padding: 18,
    borderWidth: 1,
    borderColor: "#2C405D",
    gap: 12,
    borderCurve: "continuous",
  },
  settingsEmpty: {
    backgroundColor: "#132237",
    borderRadius: 22,
    padding: 22,
    gap: 14,
    borderWidth: 1,
    borderColor: "#2C405D",
    borderCurve: "continuous",
    alignItems: "stretch",
  },
  settingsProfile: {
    backgroundColor: "#172A43",
    borderRadius: 24,
    padding: 18,
    gap: 12,
    flexDirection: "row",
    alignItems: "center",
    borderWidth: 1,
    borderColor: "#496486",
    borderCurve: "continuous",
  },
  avatarCircle: {
    height: 52,
    width: 52,
    borderRadius: 26,
    alignItems: "center",
    justifyContent: "center",
    backgroundColor: "#D7B46A",
  },
  avatarText: { color: "#101827", fontSize: 22, fontWeight: "900" },
  settingsProfileText: { flex: 1, gap: 2 },
  verifiedBadge: {
    borderRadius: 999,
    backgroundColor: "#144C39",
    paddingHorizontal: 10,
    paddingVertical: 6,
  },
  verifiedBadgeText: { color: "#8DF0BA", fontSize: 12, fontWeight: "900" },
  settingsCard: {
    backgroundColor: "#132237",
    borderRadius: 22,
    padding: 18,
    gap: 12,
    borderWidth: 1,
    borderColor: "#2C405D",
    borderCurve: "continuous",
  },
  settingsRow: {
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "flex-start",
    gap: 16,
    borderTopWidth: 1,
    borderTopColor: "#293C58",
    paddingTop: 11,
  },
  settingsLabel: {
    color: "#9CB0CD",
    fontSize: 13,
    flex: 0.38,
    textAlign: "right",
  },
  settingsValue: {
    color: "#F8FAFC",
    fontSize: 14,
    fontWeight: "800",
    flex: 0.62,
    textAlign: "left",
  },
  settingsValueCompact: { fontSize: 11, fontWeight: "600" },
  settingsValueSuccess: { color: "#63D6A0" },
  permissionList: { flexDirection: "row", flexWrap: "wrap", gap: 8 },
  permissionChip: {
    borderRadius: 999,
    backgroundColor: "#1D3453",
    borderWidth: 1,
    borderColor: "#3D5D87",
    paddingHorizontal: 11,
    paddingVertical: 8,
  },
  permissionChipText: { color: "#DDEBFF", fontSize: 12, fontWeight: "800" },
  searchRow: { flexDirection: "row", gap: 8, alignItems: "center" },
  searchInput: { flex: 1 },
  searchButton: {
    backgroundColor: "#D7B46A",
    minHeight: 54,
    paddingHorizontal: 16,
    borderRadius: 14,
    justifyContent: "center",
  },
  searchButtonText: { color: "#101827", fontWeight: "900", fontSize: 15 },
  searchResult: {
    borderTopWidth: 1,
    borderTopColor: "#2C405D",
    paddingVertical: 12,
    flexDirection: "row",
    justifyContent: "space-between",
    alignItems: "center",
  },
  selectedSearchResult: {
    backgroundColor: "#1B3150",
    borderRadius: 12,
    paddingHorizontal: 10,
  },
  searchResultName: {
    color: "#F8FAFC",
    fontSize: 15,
    fontWeight: "800",
    textAlign: "right",
  },
  countBadge: {
    color: "#D7B46A",
    fontSize: 18,
    fontWeight: "900",
    fontVariant: ["tabular-nums"],
  },
  bottomTabs: {
    position: "absolute",
    bottom: 0,
    left: 0,
    right: 0,
    height: 76,
    backgroundColor: "#0E1A2B",
    borderTopWidth: 1,
    borderTopColor: "#2C405D",
    flexDirection: "row",
    alignItems: "center",
    justifyContent: "space-around",
    paddingHorizontal: 14,
  },
  tabButton: {
    width: 82,
    height: 54,
    borderRadius: 16,
    alignItems: "center",
    justifyContent: "center",
    gap: 2,
  },
  tabButtonActive: { backgroundColor: "#1C2F4A" },
  tabIcon: { color: "#98AAC5", fontSize: 20, fontWeight: "900" },
  tabLabel: { color: "#98AAC5", fontSize: 12, fontWeight: "800" },
  tabLabelActive: { color: "#F8FAFC" },
  scanTab: {
    width: 96,
    height: 64,
    marginTop: -28,
    borderRadius: 22,
    backgroundColor: "#D7B46A",
    borderWidth: 4,
    borderColor: "#091321",
    alignItems: "center",
    justifyContent: "center",
    gap: 2,
  },
  scanTabActive: { backgroundColor: "#E8C573" },
  scanTabIcon: { color: "#101827", fontSize: 22, fontWeight: "900" },
  scanTabLabel: { color: "#101827", fontSize: 13, fontWeight: "900" },
});

const resultToneStyles = {
  success: { backgroundColor: "#145F43", borderColor: "#63D6A0" },
  warning: { backgroundColor: "#684E19", borderColor: "#E6C35F" },
  error: { backgroundColor: "#6A2C39", borderColor: "#F58B9A" },
};

import * as SecureStore from "expo-secure-store";

import type { StoredAuth, StoredFieldSession } from "./types";

const AUTH_KEY = "qentry_field_auth_v1";
const FIELD_SESSION_KEY = "qentry_field_session_v1";

async function read<T>(key: string): Promise<T | null> {
  const raw = await SecureStore.getItemAsync(key);
  if (!raw) return null;
  try {
    return JSON.parse(raw) as T;
  } catch {
    await SecureStore.deleteItemAsync(key);
    return null;
  }
}

export const secureStorage = {
  getAuth: () => read<StoredAuth>(AUTH_KEY),
  setAuth: (value: StoredAuth) => SecureStore.setItemAsync(AUTH_KEY, JSON.stringify(value)),
  clearAuth: () => SecureStore.deleteItemAsync(AUTH_KEY),
  getFieldSession: () => read<StoredFieldSession>(FIELD_SESSION_KEY),
  setFieldSession: (value: StoredFieldSession) =>
    SecureStore.setItemAsync(FIELD_SESSION_KEY, JSON.stringify(value)),
  clearFieldSession: () => SecureStore.deleteItemAsync(FIELD_SESSION_KEY),
};

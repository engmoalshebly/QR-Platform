import { getApiErrorMessage, getApiErrorCode } from '@services/http/client'
import { create } from 'zustand'

export type ToastVariant = 'success' | 'error' | 'info' | 'warning'

export interface Toast {
  id: string
  title: string
  message?: string
  variant: ToastVariant
  apiError?: unknown
}

interface ToastStore {
  toasts: Toast[]
  push: (toast: Omit<Toast, 'id'>) => void
  dismiss: (id: string) => void
}

let counter = 0

export const useToastStore = create<ToastStore>((set) => ({
  toasts: [],
  push: (toast) => {
    const id = `t${Date.now()}_${counter++}`
    set((s) => ({ toasts: [...s.toasts, { ...toast, id }] }))
    if (!toast.apiError || !getApiErrorCode(toast.apiError)) setTimeout(() => {
      set((s) => ({ toasts: s.toasts.filter((t) => t.id !== id) }))
    }, 4500)
  },
  dismiss: (id) => set((s) => ({ toasts: s.toasts.filter((t) => t.id !== id) })),
}))

export const toast = {
  apiError: (title: string, error: unknown) => useToastStore.getState().push({ title, message: getApiErrorMessage(error), apiError: error, variant: 'error' }),
  success: (title: string, message?: string) => useToastStore.getState().push({ title, message, variant: 'success' }),
  error: (title: string, message?: string) => useToastStore.getState().push({ title, message, variant: 'error' }),
  info: (title: string, message?: string) => useToastStore.getState().push({ title, message, variant: 'info' }),
  warning: (title: string, message?: string) => useToastStore.getState().push({ title, message, variant: 'warning' }),
}

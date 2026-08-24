import { AnimatePresence, motion } from 'framer-motion'
import { CheckCircle2, AlertCircle, Info, XCircle, X } from 'lucide-react'
import { useToastStore, type ToastVariant } from './toast'

const ICONS: Record<ToastVariant, typeof Info> = {
  success: CheckCircle2,
  error: AlertCircle,
  info: Info,
  warning: XCircle,
}

const TONES: Record<ToastVariant, string> = {
  success: 'toast--success',
  error: 'toast--error',
  info: 'toast--info',
  warning: 'toast--warning',
}

export function Toaster() {
  const toasts = useToastStore((s) => s.toasts)
  const dismiss = useToastStore((s) => s.dismiss)

  return (
    <div className="toaster" role="region" aria-label="الإشعارات" dir="rtl">
      <AnimatePresence>
        {toasts.map((t) => {
          const Icon = ICONS[t.variant]
          return (
            <motion.div
              key={t.id}
              layout
              initial={{ opacity: 0, y: -12, scale: 0.96 }}
              animate={{ opacity: 1, y: 0, scale: 1 }}
              exit={{ opacity: 0, scale: 0.96 }}
              transition={{ duration: 0.18 }}
              className={`toast ${TONES[t.variant]}`}
            >
              <Icon size={18} className="toast__icon" />
              <div className="toast__body">
                <p className="toast__title">{t.title}</p>
                {t.message && <p className="toast__message">{t.message}</p>}
              </div>
              <button className="toast__close" onClick={() => dismiss(t.id)} aria-label="إغلاق">
                <X size={14} />
              </button>
            </motion.div>
          )
        })}
      </AnimatePresence>
    </div>
  )
}

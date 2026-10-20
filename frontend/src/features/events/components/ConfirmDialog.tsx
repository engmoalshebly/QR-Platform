/**
 * ConfirmDialog.tsx
 * Professional animated confirmation dialog.
 * Replaces all window.confirm() calls throughout the events feature.
 */
import { motion, AnimatePresence } from 'framer-motion'
import { AlertTriangle, Trash2, X, Loader2 } from 'lucide-react'

interface Props {
  isOpen: boolean
  title: string
  message: string
  confirmLabel?: string
  cancelLabel?: string
  variant?: 'danger' | 'warning' | 'default'
  isPending?: boolean
  onConfirm: () => void
  onCancel: () => void
}

export function ConfirmDialog({
  isOpen,
  title,
  message,
  confirmLabel = 'تأكيد',
  cancelLabel = 'إلغاء',
  variant = 'default',
  isPending = false,
  onConfirm,
  onCancel,
}: Props) {
  if (!isOpen) return null

  const iconMap = {
    danger: <Trash2 size={20} />,
    warning: <AlertTriangle size={20} />,
    default: null,
  }

  const iconBg = {
    danger: 'rgba(239, 68, 68, 0.12)',
    warning: 'rgba(245, 158, 11, 0.12)',
    default: 'rgba(212, 163, 44, 0.12)',
  }

  const iconColor = {
    danger: '#fca5a5',
    warning: '#fcd34d',
    default: '#D4A32C',
  }

  const btnClass = {
    danger: 'btn btn-danger',
    warning: 'btn btn-primary',
    default: 'btn btn-primary',
  }

  return (
    <AnimatePresence>
      <motion.div
        className="dialog-overlay"
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        exit={{ opacity: 0 }}
        onClick={onCancel}
      >
        <motion.div
          className="confirm-dialog"
          initial={{ opacity: 0, scale: 0.92, y: 12 }}
          animate={{ opacity: 1, scale: 1, y: 0 }}
          exit={{ opacity: 0, scale: 0.92, y: 12 }}
          transition={{ type: 'spring', stiffness: 380, damping: 30 }}
          onClick={(e) => e.stopPropagation()}
        >
          {/* Header */}
          <div className="confirm-dialog__header">
            <div
              className="confirm-dialog__icon"
              style={{ background: iconBg[variant], color: iconColor[variant] }}
            >
              {iconMap[variant]}
            </div>
            <h3 className="confirm-dialog__title">{title}</h3>
            <button className="dialog-close" onClick={onCancel} aria-label="إغلاق">
              <X size={18} />
            </button>
          </div>

          {/* Body */}
          <p className="confirm-dialog__message">{message}</p>

          {/* Actions */}
          <div className="confirm-dialog__actions">
            <button className="btn btn-ghost" onClick={onCancel} disabled={isPending}>
              {cancelLabel}
            </button>
            <button
              className={btnClass[variant]}
              onClick={onConfirm}
              disabled={isPending}
            >
              {isPending ? (
                <>
                  <Loader2 size={15} className="spin" />
                  جاري التنفيذ…
                </>
              ) : (
                confirmLabel
              )}
            </button>
          </div>
        </motion.div>
      </motion.div>
    </AnimatePresence>
  )
}

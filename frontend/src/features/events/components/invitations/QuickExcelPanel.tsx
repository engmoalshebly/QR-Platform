import { Download, Plus, Upload, FileSpreadsheet, X, AlertCircle } from 'lucide-react'
import { Can, PERM } from '@shared/permissions'
import type { GuestImportRow } from './types'

interface QuickExcelPanelProps {
  downloadExcelTemplate: () => Promise<void>
  showSingleGuestModal: boolean
  setShowSingleGuestModal: (val: boolean) => void
  excelImportFileName: string
  clearImportedGuests: (target: 'excel' | 'design') => void
  excelImportErrors: string[]
  excelImportedGuests: GuestImportRow[]
  totalImportedGuests: number
  plannedVipCount: number
  plannedNormalCount: number
  totalInvitations: number
  handleGuestFileSelected: (file: File | null, type: 'excel') => void
  singleGuestName: string
  setSingleGuestName: (val: string) => void
  singleGuestCount: number
  setSingleGuestCount: (val: number) => void
  singleGuestClass: 'vip' | 'normal'
  setSingleGuestClass: (val: 'vip' | 'normal') => void
  addSingleGuest: () => void
  localError: string | null
  isPending: boolean
}

export function QuickExcelPanel({
  downloadExcelTemplate,
  showSingleGuestModal,
  setShowSingleGuestModal,
  excelImportFileName,
  clearImportedGuests,
  excelImportErrors,
  excelImportedGuests,
  totalImportedGuests,
  plannedVipCount,
  plannedNormalCount,
  totalInvitations,
  handleGuestFileSelected,
  singleGuestName,
  setSingleGuestName,
  singleGuestCount,
  setSingleGuestCount,
  singleGuestClass,
  setSingleGuestClass,
  addSingleGuest,
  localError,
  isPending,
}: QuickExcelPanelProps) {
  return (
    <>
      <div className="inv-import-card">
        <div className="inv-import-card__header">
          <div>
            <strong>رفع ملف الضيوف</strong>
            <span>ارفع ملف Excel يحتوي على اسم الضيف، عدد الأشخاص، ونوع التذكرة. الحد الحالي 1000 دعوة للعملية الواحدة.</span>
          </div>
          <div className="inv-import-card__header-actions">
            <Can permission={PERM.GUEST_IMPORT}>
              <button type="button" className="inv-dl-btn inv-dl-btn--zip" onClick={() => { void downloadExcelTemplate() }}>
                <Download size={15} /> تنزيل النموذج
              </button>
            </Can>
            <Can permission={PERM.GUEST_CREATE}>
              <button type="button" className="inv-quick-add-btn" onClick={() => setShowSingleGuestModal(true)}>
                <Plus size={15} /> إضافة دعوة واحدة
              </button>
            </Can>
          </div>
        </div>

        <div className="inv-import-card__actions">
          <label className="inv-upload-btn">
            <Upload size={15} /> اختيار ملف Excel
            <input
              type="file"
              accept=".xlsx,.csv"
              onClick={(e) => {
                e.currentTarget.value = ''
              }}
              onChange={(e) => handleGuestFileSelected(e.target.files?.[0] ?? null, 'excel')}
              hidden
            />
          </label>
          {excelImportFileName && (
            <div className="inv-upload-file">
              <FileSpreadsheet size={15} />
              <span>{excelImportFileName}</span>
              <button type="button" className="inv-upload-file__clear" onClick={() => clearImportedGuests('excel')}>
                <X size={14} />
              </button>
            </div>
          )}
        </div>

        {!!excelImportErrors.length && (
          <div className="inv-import-errors">
            {excelImportErrors.slice(0, 5).map((msg) => (
              <div key={msg} className="inv-import-errors__item">
                {msg}
              </div>
            ))}
          </div>
        )}

        {!!excelImportedGuests.length && (
          <>
            <div className="inv-import-stats">
              <div>
                <strong>{totalImportedGuests}</strong>
                <span>سجل/ضيف</span>
              </div>
              <div>
                <strong>{plannedVipCount}</strong>
                <span>عدد أشخاص VIP</span>
              </div>
              <div>
                <strong>{plannedNormalCount}</strong>
                <span>عدد الأشخاص العاديين</span>
              </div>
              <div>
                <strong>{totalInvitations}</strong>
                <span>إجمالي البطاقات</span>
              </div>
            </div>
            <div className="inv-import-preview">
              {excelImportedGuests.slice(0, 5).map((guest, index) => (
                <div key={`${guest.guest_name}-${index}`} className="inv-import-preview__row">
                  <strong>{guest.guest_name}</strong>
                  <span>
                    دعوة واحدة · {guest.ticket_class === 'vip' ? 'VIP' : 'عادي'} · {guest.invitation_count} شخص
                  </span>
                </div>
              ))}
              {excelImportedGuests.length > 5 && (
                <div className="inv-import-preview__more">+{excelImportedGuests.length - 5} صفوف إضافية</div>
              )}
            </div>
          </>
        )}
      </div>

      {showSingleGuestModal && (
        <div className="inv-quick-modal-overlay" role="dialog" aria-modal="true">
          <div className="inv-quick-modal">
            <div className="inv-quick-modal__header">
              <div>
                <h3>إضافة دعوة واحدة</h3>
                <p>أدخل الاسم ونوع التذكرة ثم أضفها إلى قائمة Excel الحالية.</p>
              </div>
              <button type="button" className="inv-quick-modal__close" onClick={() => setShowSingleGuestModal(false)}>
                <X size={16} />
              </button>
            </div>

            <div className="inv-quick-modal__body">
              <div>
                <label className="inv-label">اسم الشخص</label>
                <input
                  type="text"
                  value={singleGuestName}
                  onChange={(e) => setSingleGuestName(e.target.value)}
                  className="inv-input"
                  placeholder="مثال: أحمد محمد"
                  disabled={isPending}
                />
              </div>

              <div>
                <label className="inv-label">عدد الأشخاص</label>
                <input
                  type="number"
                  min={1}
                  max={100}
                  value={singleGuestCount}
                  onChange={(e) => setSingleGuestCount(Number(e.target.value))}
                  className="inv-input"
                  placeholder="1"
                  disabled={isPending}
                />
              </div>

              <div>
                <label className="inv-label">نوع التذكرة</label>
                <div className="inv-quick-modal__chips">
                  <button
                    type="button"
                    className={`inv-chip ${singleGuestClass === 'normal' ? 'inv-chip--active' : ''}`}
                    onClick={() => setSingleGuestClass('normal')}
                    disabled={isPending}
                  >
                    عادي
                  </button>
                  <button
                    type="button"
                    className={`inv-chip ${singleGuestClass === 'vip' ? 'inv-chip--active' : ''}`}
                    onClick={() => setSingleGuestClass('vip')}
                    disabled={isPending}
                  >
                    VIP
                  </button>
                </div>
              </div>

              {localError && (
                <div className="inv-toast inv-toast--error">
                  <AlertCircle size={16} /> {localError}
                </div>
              )}
            </div>

            <div className="inv-quick-modal__actions">
              <button type="button" className="inv-modal__close" onClick={() => setShowSingleGuestModal(false)}>
                إلغاء
              </button>
              <Can permission={PERM.GUEST_CREATE}>
                <button type="button" className="inv-upload-btn" onClick={addSingleGuest} disabled={isPending}>
                  <Plus size={15} /> إضافة
                </button>
              </Can>
            </div>
          </div>
        </div>
      )}
    </>
  )
}

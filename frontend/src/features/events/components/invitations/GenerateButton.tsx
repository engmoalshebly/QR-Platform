import { DownloadFileButton } from '@components/DownloadFileButton'
import { Loader2, Printer, AlertCircle, CheckCircle2, Download } from 'lucide-react'
import { Can, PERM } from '@shared/permissions'
import { GenerationOperationTracker } from './GenerationOperationTracker'

interface GenerateButtonProps {
  handleGenerate: () => void
  isFormValid: boolean
  isPending: boolean
  totalInvitations: number
  totalPeople?: number
  canExport?: boolean
  localError: string | null
  isError: boolean
  error: any
  data: any
}

export function GenerateButton({
  handleGenerate,
  isFormValid,
  isPending,
  totalInvitations,
  totalPeople,
  canExport,
  localError,
  isError,
  error,
  data,
}: GenerateButtonProps) {
  return (
    <>
      <Can permission={PERM.INV_GENERATE}>
        <button
          onClick={handleGenerate}
          disabled={!isFormValid || isPending}
          className="inv-generate-btn"
        >
          {isPending ? (
            <>
              <Loader2 size={18} className="animate-spin" /> جاري إنشاء الدعوات...
            </>
          ) : (
            <>
              <Printer size={18} /> إنشاء الدعوات ({totalInvitations} دعوة)
            </>
          )}
        </button>
      </Can>

      {totalPeople !== undefined && <p className="inv-hint">{totalInvitations} بطاقة دخول · {totalPeople} شخص{canExport === false ? ' · إنشاء الدعوات دون ملفات PDF أو ZIP' : ''}</p>}
      {totalInvitations > 1000 && <p role="alert" className="inv-hint">الحد الحالي 1000 دعوة للعملية الواحدة. قسّم البيانات إلى دفعات أصغر.</p>}
      {/* Error */}
      {(localError || (isError && error)) && (
        <div className="inv-toast inv-toast--error">
          <AlertCircle size={16} /> {localError || (error as any)?.message}
        </div>
      )}

      {/* Durable contract: accepted (202) is not finished; follow the operation itself. */}
      {data?.operation && <GenerationOperationTracker operationId={data.operation.id} />}

      {/* Success Result */}
      {data?.success && (
        <div className="inv-result">
          <div className="inv-result__info">
            <CheckCircle2 size={20} />
            <div>
              <strong>تم إنشاء الدعوات بنجاح!</strong>
              <span>
                {data.total_invitations} دعوة في {data.generation_time_ms}ms
              </span>
            </div>
          </div>
          <Can permission="invitations.export">
            <div className="inv-result__actions">
              {data.pdf_url && (
                <DownloadFileButton url={data.pdf_url} filename="invitations.pdf" className="inv-dl-btn inv-dl-btn--pdf">
                  <Download size={16} /> PDF ({data.pdf_size_mb?.toFixed(2)} MB)
                </DownloadFileButton>
              )}
              {data.zip_url && (
                <DownloadFileButton url={data.zip_url} filename="invitations.zip" className="inv-dl-btn inv-dl-btn--zip">
                  <Download size={16} /> ZIP ({data.zip_size_mb?.toFixed(2)} MB)
                </DownloadFileButton>
              )}
            </div>
          </Can>
        </div>
      )}
    </>
  )
}

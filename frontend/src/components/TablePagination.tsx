import { useEffect, useState } from "react";
import "./table-pagination.css";

export function TablePagination({
  total,
  offset,
  limit,
  onOffset,
  onLimit,
  disabled = false,
  label = "صفحات الدعوات",
}: {
  total: number;
  offset: number;
  limit: number;
  onOffset: (value: number) => void;
  onLimit: (value: number) => void;
  disabled?: boolean;
  label?: string;
}) {
  const page = Math.floor(offset / limit) + 1,
    pages = Math.max(1, Math.ceil(total / limit));
  const [jump, setJump] = useState(String(page));
  useEffect(() => setJump(String(page)), [page]);
  const numeric = Number(jump);
  return (
    <nav className="table-pagination" aria-label={label} dir="rtl">
      <span className="table-pagination__count">
        {total
          ? `عرض ${(offset + 1).toLocaleString("ar")}–${Math.min(offset + limit, total).toLocaleString("ar")} من ${total.toLocaleString("ar")} نتيجة`
          : "لا توجد نتائج"}
      </span>
      <div className="table-pagination__controls">
        <label>
          صفوف الصفحة
          <select
            aria-label={`${label}: صفوف الصفحة`}
            value={limit}
            disabled={disabled}
            onChange={(e) => onLimit(Number(e.target.value))}
          >
            <option value={25}>25</option>
            <option value={50}>50</option>
            <option value={100}>100</option>
          </select>
        </label>
        <button
          disabled={disabled || offset === 0}
          onClick={() => onOffset(Math.max(0, offset - limit))}
        >
          السابق
        </button>
        <span>
          صفحة {page.toLocaleString("ar")} من {pages.toLocaleString("ar")}
        </span>
        <button
          disabled={disabled || offset + limit >= total}
          onClick={() => onOffset(offset + limit)}
        >
          التالي
        </button>
        {pages > 3 && (
          <form
            onSubmit={(e) => {
              e.preventDefault();
              if (Number.isInteger(numeric) && numeric >= 1 && numeric <= pages)
                onOffset((numeric - 1) * limit);
            }}
          >
            <input
              type="number"
              aria-label={`${label}: الانتقال إلى صفحة`}
              min={1}
              max={pages}
              value={jump}
              disabled={disabled}
              onChange={(e) => setJump(e.target.value)}
            />
            <button
              disabled={
                disabled ||
                !Number.isInteger(numeric) ||
                numeric < 1 ||
                numeric > pages
              }
            >
              انتقال
            </button>
          </form>
        )}
      </div>
    </nav>
  );
}

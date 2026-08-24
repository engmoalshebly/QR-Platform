-- Phase 1 operations enhancements: subtasks, comments, manager approval, per-type task templates.

-- ── Extend event_operation_tasks: parent (subtasks), start date, manager approval ──
ALTER TABLE public.event_operation_tasks
    ADD COLUMN IF NOT EXISTS parent_task_id UUID REFERENCES public.event_operation_tasks(id) ON DELETE CASCADE;
ALTER TABLE public.event_operation_tasks
    ADD COLUMN IF NOT EXISTS start_at TIMESTAMPTZ;
ALTER TABLE public.event_operation_tasks
    ADD COLUMN IF NOT EXISTS approval_required BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE public.event_operation_tasks
    ADD COLUMN IF NOT EXISTS approved_by UUID REFERENCES public.profiles(id) ON DELETE SET NULL;
ALTER TABLE public.event_operation_tasks
    ADD COLUMN IF NOT EXISTS approved_at TIMESTAMPTZ;

-- A subtask points at its parent; top-level tasks have NULL parent_task_id.
CREATE INDEX IF NOT EXISTS idx_operation_tasks_parent ON public.event_operation_tasks(parent_task_id);

-- ── Task comments ──
CREATE TABLE IF NOT EXISTS public.event_operation_task_comments (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    task_id UUID NOT NULL REFERENCES public.event_operation_tasks(id) ON DELETE CASCADE,
    author_id UUID NOT NULL REFERENCES public.profiles(id) ON DELETE CASCADE,
    body TEXT NOT NULL CHECK (length(trim(body)) >= 1),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_task_comments_task ON public.event_operation_task_comments(task_id, created_at);

-- ── Per-event-type task templates ──
-- Templates are seeded once and cloned into an operation when it is provisioned.
-- event_type_key matches organizer_booking_requests.event_type loosely (free-text),
-- so the match is best-effort by the event_type_name; the API also falls back to a
-- 'default' template when no type-specific one exists.
CREATE TABLE IF NOT EXISTS public.event_task_templates (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    event_type_key TEXT NOT NULL,
    title TEXT NOT NULL CHECK (length(trim(title)) >= 2),
    description TEXT,
    priority TEXT NOT NULL DEFAULT 'medium' CHECK (priority IN ('low','medium','high','urgent')),
    sort_order INTEGER NOT NULL DEFAULT 0,
    approval_required BOOLEAN NOT NULL DEFAULT FALSE,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_task_template_type_title
    ON public.event_task_templates(event_type_key, title);

-- ── Seed a default template + a wedding template (Phase 1 starter set) ──
INSERT INTO public.event_task_templates(event_type_key, title, description, priority, sort_order, approval_required) VALUES
    ('default', 'استلام تفاصيل الحفل والاتصال بالعميل', 'مراجعة المتطلبات وتأكيد نطاق العمل مع المؤسسة.', 'high', 10, FALSE),
    ('default', 'زيارة الموقع المعاينة', 'معاينة الموقع وتدوين القيود اللوجستية.', 'medium', 20, FALSE),
    ('default', 'تجهيز المعدات والتصاريح', 'تجهيز المعدات واستخراج التصاريح اللازمة.', 'high', 30, FALSE),
    ('default', 'توزيع المهام على الفريق', 'إسناد المهام لأعضاء الفريق حسب التخصص.', 'medium', 40, FALSE),
    ('default', 'التنفيذ يوم الحفل', 'حضور الفريق وتنفيذ المهام في موعدها.', 'urgent', 50, TRUE),
    ('default', 'التفكيك والإغلاق', 'تفكيك التجهيزات وتسليم الموقع.', 'medium', 60, FALSE),
    ('default', 'التقرير الختامي', 'إعداد التقرير الختامي للحفل وإرساله للعميل.', 'medium', 70, TRUE),
    ('زفاف', 'التنسيق مع قاعة الحفل', 'تأكيد مواعيد التجهيز والتفكيك مع إدارة القاعة.', 'high', 15, FALSE),
    ('زفاف', 'تنسيق دخول العروسين', 'تحديد مواعيد وتسلسل دخول العروسين والضيوف.', 'high', 45, FALSE),
    ('مؤتمر', 'تنسيق المتحدثين', 'تأكيد حضور المتحدثين وجدولة الجلسات.', 'high', 25, FALSE),
    ('مؤتمر', 'فحص الصوت والعرض', 'اختبار أنظمة الصوت والعرض قبل بدء المؤتمر.', 'high', 35, TRUE)
ON CONFLICT DO NOTHING;

INSERT INTO public.app_schema_migrations(version, name)
VALUES (25, 'phase1_tasks_enhancements') ON CONFLICT (version) DO NOTHING;

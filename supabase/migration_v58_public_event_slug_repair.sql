-- Migration v58: repair public event slugs that were generated from titles
-- containing no ASCII characters (for example Arabic-only titles).

UPDATE public.events
SET slug = 'event-' || COALESCE(NULLIF(trim(BOTH '-' FROM slug), ''), left(id::text, 8))
WHERE slug IS NULL OR trim(BOTH '-' FROM slug) = '' OR slug LIKE '-%' OR slug LIKE '%-';


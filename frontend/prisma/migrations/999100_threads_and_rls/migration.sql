-- Create tables if not exists (idempotent style where possible)
DO $$
BEGIN
  IF to_regclass('public.threads') IS NULL THEN
    CREATE TABLE public.threads (
      id          TEXT PRIMARY KEY,
      status      TEXT NOT NULL DEFAULT 'active',
      created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
      updated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
      user_id     TEXT
    );
  END IF;

  IF to_regclass('public.thread_messages') IS NULL THEN
    CREATE TABLE public.thread_messages (
      id          BIGSERIAL PRIMARY KEY,
      thread_id   TEXT NOT NULL REFERENCES public.threads(id) ON DELETE CASCADE,
      role        TEXT NOT NULL,
      content     JSONB NOT NULL,
      created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
      user_id     TEXT
    );
  END IF;
END $$;

-- Ensure required columns exist on pre-existing tables (backfill columns if tables already existed)
DO $$
BEGIN
  IF to_regclass('public.threads') IS NOT NULL AND NOT EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_schema='public' AND table_name='threads' AND column_name='user_id'
  ) THEN
    ALTER TABLE public.threads ADD COLUMN user_id TEXT;
  END IF;

  IF to_regclass('public.thread_messages') IS NOT NULL AND NOT EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_schema='public' AND table_name='thread_messages' AND column_name='user_id'
  ) THEN
    ALTER TABLE public.thread_messages ADD COLUMN user_id TEXT;
  END IF;
END $$;

-- Indexes
CREATE INDEX IF NOT EXISTS idx_thread_messages_thread_id ON public.thread_messages(thread_id);
CREATE INDEX IF NOT EXISTS idx_thread_messages_thread_created ON public.thread_messages(thread_id, created_at);
CREATE INDEX IF NOT EXISTS idx_thread_messages_user ON public.thread_messages(user_id, thread_id, created_at);
CREATE INDEX IF NOT EXISTS idx_threads_user_updated ON public.threads(user_id, updated_at);

-- Enable RLS
ALTER TABLE IF EXISTS public.threads ENABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS public.thread_messages ENABLE ROW LEVEL SECURITY;

-- Policies for threads
DROP POLICY IF EXISTS threads_select ON public.threads;
CREATE POLICY threads_select ON public.threads FOR SELECT USING (user_id = current_setting('app.user_id', true));
DROP POLICY IF EXISTS threads_insert ON public.threads;
CREATE POLICY threads_insert ON public.threads FOR INSERT WITH CHECK (user_id = current_setting('app.user_id', true));
DROP POLICY IF EXISTS threads_update ON public.threads;
CREATE POLICY threads_update ON public.threads FOR UPDATE USING (user_id = current_setting('app.user_id', true)) WITH CHECK (user_id = current_setting('app.user_id', true));
DROP POLICY IF EXISTS threads_delete ON public.threads;
CREATE POLICY threads_delete ON public.threads FOR DELETE USING (user_id = current_setting('app.user_id', true));

-- Policies for thread_messages
DROP POLICY IF EXISTS thread_messages_select ON public.thread_messages;
CREATE POLICY thread_messages_select ON public.thread_messages FOR SELECT USING (user_id = current_setting('app.user_id', true));
DROP POLICY IF EXISTS thread_messages_insert ON public.thread_messages;
CREATE POLICY thread_messages_insert ON public.thread_messages FOR INSERT WITH CHECK (user_id = current_setting('app.user_id', true));
DROP POLICY IF EXISTS thread_messages_update ON public.thread_messages;
CREATE POLICY thread_messages_update ON public.thread_messages FOR UPDATE USING (user_id = current_setting('app.user_id', true)) WITH CHECK (user_id = current_setting('app.user_id', true));
DROP POLICY IF EXISTS thread_messages_delete ON public.thread_messages;
CREATE POLICY thread_messages_delete ON public.thread_messages FOR DELETE USING (user_id = current_setting('app.user_id', true));



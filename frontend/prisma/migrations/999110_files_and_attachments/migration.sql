-- Create files table
DO $$
BEGIN
  IF to_regclass('public.files') IS NULL THEN
    CREATE TABLE public.files (
      id          TEXT PRIMARY KEY,
      user_id     TEXT NOT NULL,
      kind        TEXT NOT NULL,
      bucket      TEXT NOT NULL,
      object_key  TEXT NOT NULL,
      etag        TEXT,
      sha256      TEXT,
      size_bytes  BIGINT NOT NULL,
      mime        TEXT NOT NULL,
      status      TEXT NOT NULL DEFAULT 'ready',
      meta        JSONB,
      created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
      updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
    );
  END IF;
END $$;

-- Indexes for files
CREATE UNIQUE INDEX IF NOT EXISTS ux_files_user_sha ON public.files(user_id, sha256);
CREATE INDEX IF NOT EXISTS idx_files_user_created ON public.files(user_id, created_at);
CREATE INDEX IF NOT EXISTS idx_files_kind_created ON public.files(kind, created_at);

-- RLS for files
ALTER TABLE IF EXISTS public.files ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS files_select ON public.files;
CREATE POLICY files_select ON public.files FOR SELECT USING (user_id = current_setting('app.user_id', true));
DROP POLICY IF EXISTS files_insert ON public.files;
CREATE POLICY files_insert ON public.files FOR INSERT WITH CHECK (user_id = current_setting('app.user_id', true));
DROP POLICY IF EXISTS files_update ON public.files;
CREATE POLICY files_update ON public.files FOR UPDATE USING (user_id = current_setting('app.user_id', true)) WITH CHECK (user_id = current_setting('app.user_id', true));
DROP POLICY IF EXISTS files_delete ON public.files;
CREATE POLICY files_delete ON public.files FOR DELETE USING (user_id = current_setting('app.user_id', true));

-- Create message_attachments table
DO $$
BEGIN
  IF to_regclass('public.message_attachments') IS NULL THEN
    CREATE TABLE public.message_attachments (
      id          TEXT PRIMARY KEY,
      messageId   TEXT NOT NULL,
      fileId      TEXT NOT NULL,
      partIndex   INTEGER NOT NULL,
      created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
    );
  END IF;
END $$;

-- Indexes for message_attachments
CREATE INDEX IF NOT EXISTS idx_msg_attach_message_part ON public.message_attachments(messageId, partIndex);
CREATE INDEX IF NOT EXISTS idx_msg_attach_file ON public.message_attachments(fileId);

-- RLS for message_attachments (inherit visibility from files via join at query time)
ALTER TABLE IF EXISTS public.message_attachments ENABLE ROW LEVEL SECURITY;
-- Minimal policies that require app layer to set user_id filter when joining to files
DROP POLICY IF EXISTS msg_attach_select ON public.message_attachments;
CREATE POLICY msg_attach_select ON public.message_attachments FOR SELECT USING (true);
DROP POLICY IF EXISTS msg_attach_ins ON public.message_attachments;
CREATE POLICY msg_attach_ins ON public.message_attachments FOR INSERT WITH CHECK (true);
DROP POLICY IF EXISTS msg_attach_upd ON public.message_attachments;
CREATE POLICY msg_attach_upd ON public.message_attachments FOR UPDATE USING (true) WITH CHECK (true);
DROP POLICY IF EXISTS msg_attach_del ON public.message_attachments;
CREATE POLICY msg_attach_del ON public.message_attachments FOR DELETE USING (true);



-- Add userId columns to Conversation and Message, and create indexes to match schema.prisma

-- Conversation.userId (nullable for existing rows)
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_schema = 'public' AND table_name = 'Conversation' AND column_name = 'userId'
  ) THEN
    ALTER TABLE "public"."Conversation" ADD COLUMN "userId" TEXT;
  END IF;
END $$;

-- Message.userId (nullable for existing rows)
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_schema = 'public' AND table_name = 'Message' AND column_name = 'userId'
  ) THEN
    ALTER TABLE "public"."Message" ADD COLUMN "userId" TEXT;
  END IF;
END $$;

-- Indexes matching schema.prisma maps
-- Conversation: @@index([userId, updatedAt], map: "idx_conversations_user_updated")
CREATE INDEX IF NOT EXISTS "idx_conversations_user_updated" ON "public"."Conversation" ("userId", "updatedAt" DESC);

-- Message: @@index([userId, createdAt], map: "idx_messages_user_created")
CREATE INDEX IF NOT EXISTS "idx_messages_user_created" ON "public"."Message" ("userId", "createdAt");



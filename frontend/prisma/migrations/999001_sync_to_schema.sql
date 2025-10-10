-- AlterTable
ALTER TABLE "public"."documents" ADD COLUMN     "uri" TEXT,
ADD COLUMN     "user_id" TEXT;

-- CreateTable
CREATE TABLE "public"."AudioInput" (
    "id" TEXT NOT NULL,
    "filename" TEXT NOT NULL,
    "mime" TEXT NOT NULL,
    "durationMs" INTEGER,
    "sizeBytes" BIGINT NOT NULL,
    "sha256" TEXT NOT NULL,
    "storage" TEXT NOT NULL,
    "url" TEXT,
    "blob" BYTEA,
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "AudioInput_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "public"."AsrTranscript" (
    "id" TEXT NOT NULL,
    "audioId" TEXT NOT NULL,
    "model" TEXT NOT NULL,
    "lang" TEXT,
    "text" TEXT NOT NULL,
    "wordsJson" JSONB,
    "latencyMs" INTEGER,
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "AsrTranscript_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "public"."TtsCache" (
    "id" TEXT NOT NULL,
    "textHash" TEXT NOT NULL,
    "text" TEXT NOT NULL,
    "voice" TEXT NOT NULL,
    "speed" DECIMAL(65,30) NOT NULL DEFAULT 1.0,
    "model" TEXT NOT NULL,
    "storage" TEXT NOT NULL,
    "url" TEXT,
    "blob" BYTEA,
    "mime" TEXT NOT NULL DEFAULT 'audio/mpeg',
    "sizeBytes" BIGINT,
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "TtsCache_pkey" PRIMARY KEY ("id")
);

-- CreateIndex
CREATE UNIQUE INDEX "AudioInput_sha256_key" ON "public"."AudioInput"("sha256");

-- CreateIndex
CREATE INDEX "AsrTranscript_audioId_idx" ON "public"."AsrTranscript"("audioId");

-- CreateIndex
CREATE UNIQUE INDEX "TtsCache_textHash_key" ON "public"."TtsCache"("textHash");

-- CreateIndex
CREATE INDEX "idx_documents_user_created" ON "public"."documents"("user_id", "created_at");

-- CreateIndex
CREATE INDEX "idx_documents_status" ON "public"."documents"("status");

-- AddForeignKey
ALTER TABLE "public"."AsrTranscript" ADD CONSTRAINT "AsrTranscript_audioId_fkey" FOREIGN KEY ("audioId") REFERENCES "public"."AudioInput"("id") ON DELETE CASCADE ON UPDATE CASCADE;


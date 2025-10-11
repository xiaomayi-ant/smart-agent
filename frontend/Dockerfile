FROM node:20-alpine AS base
# libc6-compat improves compatibility with some native deps
# openssl is required by Prisma in all stages
RUN apk add --no-cache libc6-compat openssl && corepack enable
WORKDIR /app

# -----------------------------
# deps: install workspace deps (only frontend)
# -----------------------------
FROM base AS deps
WORKDIR /app
ENV NODE_ENV=development \
    NEXT_TELEMETRY_DISABLED=1 \
    PRISMA_SKIP_POSTINSTALL_GENERATE=true

# Workspace manifests
COPY pnpm-workspace.yaml pnpm-lock.yaml package.json turbo.json ./
# Frontend manifest only (speeds up install caching)
COPY frontend/package.json frontend/package.json

# Install only the frontend workspace dependencies (incl. dev deps for build/migrate)
RUN pnpm install --frozen-lockfile --filter ./frontend...

# -----------------------------
# builder: generate prisma client + next build (standalone)
# -----------------------------
FROM deps AS builder
WORKDIR /app/frontend
ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1

# Copy source code
COPY frontend ./
RUN mkdir -p public

# Generate Prisma Client for the container platform, then build Next.js
RUN pnpm prisma generate
RUN pnpm build

# -----------------------------
# runner: production runtime using Next standalone output
# -----------------------------
FROM node:20-alpine AS runner
RUN apk add --no-cache openssl
WORKDIR /app
ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    PORT=3000
EXPOSE 3000

# Copy standalone server and static assets
# Next.js standalone 会在 .next/standalone 中复制整个项目结构
COPY --from=builder /app/frontend/.next/standalone ./
# 复制 static 到 frontend 子目录下（保持原有结构）
COPY --from=builder /app/frontend/.next/static ./frontend/.next/static
COPY --from=builder /app/frontend/public ./frontend/public

# Prisma schema is not needed at runtime, but keeping it doesn't harm
COPY --from=builder /app/frontend/prisma ./frontend/prisma

CMD ["node", "frontend/server.js"]

# -----------------------------
# migrator: ephemeral job to run `prisma migrate deploy`
# -----------------------------
FROM deps AS migrator
WORKDIR /app/frontend
ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1

# Only schema + migrations are required for deploy
COPY frontend/prisma ./prisma

# prisma CLI is available via devDependency installed in deps stage
CMD ["pnpm", "prisma", "migrate", "deploy"]


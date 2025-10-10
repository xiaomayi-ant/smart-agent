## Multi-stage build for Next.js app with Prisma client

# ---------- Builder ----------
FROM node:20-slim AS builder

ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1

WORKDIR /app

COPY package.json ./
COPY tsconfig.json ./
COPY next.config.mjs ./
COPY postcss.config.mjs ./
COPY tailwind.config.ts ./
COPY prisma ./prisma
RUN npm install

# Generate Prisma Client (used by API routes)
RUN npx prisma generate

COPY app ./app
COPY lib ./lib
COPY components ./components
COPY public ./public

RUN npm run build


# ---------- Runner ----------
FROM node:20-slim AS runner

ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1

WORKDIR /app

COPY --from=builder /app/package.json ./package.json
COPY --from=builder /app/node_modules ./node_modules
COPY --from=builder /app/.next ./.next
COPY --from=builder /app/public ./public
COPY --from=builder /app/next.config.mjs ./next.config.mjs
COPY --from=builder /app/prisma ./prisma

# ---------- Prisma-only stage (for migrations) ----------
FROM node:20-slim AS prisma
ENV NODE_ENV=production NEXT_TELEMETRY_DISABLED=1
WORKDIR /app
COPY package.json ./package.json
RUN npm install --include=dev
COPY prisma ./prisma
RUN npx prisma generate
CMD ["npx", "prisma", "migrate", "deploy"]

EXPOSE 3000

CMD ["npm", "run", "start", "--", "-p", "3000"]



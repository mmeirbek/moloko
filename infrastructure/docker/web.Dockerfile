# syntax=docker/dockerfile:1
# moloko frontend (Next.js standalone). Build context: repository root.

FROM node:22.23.4-alpine AS builder
ENV NEXT_TELEMETRY_DISABLED=1
WORKDIR /app
# Install workspace dependencies from the lockfile only (cached layer).
COPY package.json package-lock.json ./
COPY apps/web/package.json apps/web/
COPY packages/shared-types/package.json packages/shared-types/
RUN npm ci --no-audit --no-fund
COPY packages/shared-types packages/shared-types
COPY apps/web apps/web
RUN npm run build -w @moloko/web

FROM node:22.23.4-alpine AS runtime
ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    PORT=3000 \
    HOSTNAME=0.0.0.0
RUN addgroup -S -g 10001 app && adduser -S -u 10001 -G app app
WORKDIR /app
COPY --from=builder /app/apps/web/.next/standalone ./
COPY --from=builder /app/apps/web/.next/static ./apps/web/.next/static
COPY --from=builder /app/apps/web/public ./apps/web/public
USER app
EXPOSE 3000
CMD ["node", "apps/web/server.js"]

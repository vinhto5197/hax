# syntax=docker/dockerfile:1.7
FROM node:22-alpine AS build
WORKDIR /app
# Manifests first so the install layer survives source edits.
COPY apps/web/package.json apps/web/package-lock.json ./
RUN npm ci
COPY apps/web ./
# NEXT_PUBLIC_* is inlined into the browser bundle at build time, so it must be
# known here; empty means same-origin /api (the production topology).
ARG NEXT_PUBLIC_API_URL=
ENV NEXT_PUBLIC_API_URL=$NEXT_PUBLIC_API_URL NEXT_TELEMETRY_DISABLED=1
RUN npm run build

FROM node:22-alpine AS runtime
WORKDIR /app
# node server.js runs without the next CLI, so nothing else sets NODE_ENV.
ENV NODE_ENV=production NEXT_TELEMETRY_DISABLED=1 PORT=3000 HOSTNAME=0.0.0.0
RUN addgroup -S hax && adduser -S -G hax hax
# The standalone output is the traced server + only the modules it imports.
COPY --from=build --chown=hax:hax /app/.next/standalone ./
COPY --from=build --chown=hax:hax /app/.next/static ./.next/static
COPY --from=build --chown=hax:hax /app/public ./public
USER hax
EXPOSE 3000
CMD ["node", "server.js"]

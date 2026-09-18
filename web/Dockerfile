# Next.js web image (#429). Built from the web/ context, not the repo root.
#
# Node 24 (the active LTS line) to match CI. The app is a true BFF — there is not a single NEXT_PUBLIC_* var, and
# API_BASE_URL is read server-side at request time — so nothing here is baked in at build
# time and one image is portable across every environment.

FROM node:24-slim AS builder

WORKDIR /app

# node:24-slim bundles npm 11, which reads this lockfile differently from the npm 10 CI
# validates it with (see web/README.md). Pin the same version CI's NPM_VERSION does, and
# assert it, so the image is installed by the installer that judged the lockfile.
ARG NPM_VERSION=10.9.8
RUN npm install -g "npm@${NPM_VERSION}" && test "$(npm -v)" = "${NPM_VERSION}"

# npm ci needs both files and nothing else; keeping this ahead of the source copy means a
# source-only change reuses the install layer.
COPY package.json package-lock.json ./
RUN npm ci

COPY . .

# Fails the image build on a type error. Since #426 the `web` CI job typechecks too, so
# this is no longer the only automated check — but it is the one that governs the artifact
# that actually ships. A broken frontend should not become an image even if someone
# reorders or trims the CI job.
RUN npm run typecheck && npm run build


FROM node:24-slim AS runtime

ENV NODE_ENV=production \
    PORT=3000 \
    HOSTNAME=0.0.0.0

WORKDIR /app

# The standalone output already contains the traced node_modules subset and the server
# entrypoint; static/ and public/ are the two things it does not carry.
COPY --from=builder --chown=node:node /app/.next/standalone ./
COPY --from=builder --chown=node:node /app/.next/static ./.next/static
COPY --from=builder --chown=node:node /app/public ./public

USER node

EXPOSE 3000

# node:slim has no curl, and adding one for a healthcheck is a lot of image for a GET.
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD node -e "fetch('http://127.0.0.1:3000/').then(r=>process.exit(r.ok?0:1)).catch(()=>process.exit(1))"

CMD ["node", "server.js"]

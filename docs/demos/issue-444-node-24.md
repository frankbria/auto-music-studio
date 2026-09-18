# Issue #444 — web image and CI on Node 24 LTS

*2026-09-18T15:38:15Z*

Criterion 1: `docker compose up` builds and runs the web container on Node 24. The stack was brought up under project `ams444` on spare ports (web 13044) with `docker compose -p ams444 up -d --build`.

```bash
docker exec ams444-web-1 node -v; docker inspect -f "health={{.State.Health.Status}}" ams444-web-1; curl -s -o /dev/null -w "GET / -> %{http_code}\n" http://127.0.0.1:13044/
```

```output
v24.21.0
health=healthy
GET / -> 200
```

The builder installs with npm 10.9.8, the same npm CI's lockfile gate uses. Without the pin, node:24-slim would use its bundled npm:

```bash
docker run --rm node:24-slim npm -v; docker run --rm --entrypoint sh acemusic-web:local -c "grep -c . /dev/null >/dev/null; echo image-node=\$(node -v)"; grep -n "NPM_VERSION\|FROM node" web/Dockerfile
```

```output
11.19.0
image-node=v24.21.0
7:FROM node:24-slim AS builder
12:# validates it with (see web/README.md). Pin the same version CI's NPM_VERSION does, and
14:ARG NPM_VERSION=10.9.8
15:RUN npm install -g "npm@${NPM_VERSION}" && test "$(npm -v)" = "${NPM_VERSION}"
31:FROM node:24-slim AS runtime
```

Criterion 2: CI's Node version matches the image's.

```bash
grep -n "node-version" .github/workflows/ci.yml; grep -n "^FROM" web/Dockerfile
```

```output
107:          node-version: "24"
161:          node-version: "24"
7:FROM node:24-slim AS builder
31:FROM node:24-slim AS runtime
```

Criterion 3: Dependabot does not propose non-LTS Node majors for /web. Already true on main since #466, which ignores every node semver-major for /web. That is stricter than an odd-major deny-list, and it needs no updates when 27 and 29 appear.

```bash
sed -n "/directory: \"\/web\"/,\$p" .github/dependabot.yml | grep -A12 "docker" | tail -8
```

```output
    cooldown:
      default-days: 14
    ignore:
      # Dependabot proposes the newest node major, LTS or not (#457 offered 26 while it was
      # still a Current release). The runtime major is chosen by hand, to an LTS line, and
      # in one change with ci.yml's node-version and jsdom's Node floor so the image and CI
      # never diverge. Patch/minor moves inside the chosen line are still welcome.
      - dependency-name: "node"
```

Web suite on Node 24 (local), same as CI will run:

```bash
cd web && node -v && npx vitest run 2>&1 | grep -E "Test Files|Tests "
```

```output
v24.12.0
 Test Files  212 passed (212)
      Tests  1700 passed (1700)
```

# waf-panel frontend image.
# WHY: build with node, serve dist/ with nginx-alpine.

FROM node:20-alpine AS builder
WORKDIR /app

# WHY: only copy package.json — NOT the lockfile.
#      Lockfiles generated on Windows host pin OS-specific native binaries
#      (@rollup/rollup-win32-x64-msvc, @esbuild/win32-x64). Reusing such a
#      lockfile inside a Linux container makes `npm install` skip the linux
#      native of rollup/esbuild and the build fails.
#      Letting npm resolve fresh inside the container picks linux binaries.
# REF: npm/cli#4828, rollup#4930
COPY package.json ./
RUN npm install --no-audit --no-fund --include=optional

COPY . .
RUN npm run build

# ── runtime ──────────────────────────────────────────────
FROM nginx:1.27-alpine
COPY --from=builder /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80

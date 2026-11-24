# Frontend image: Next.js dev server (B08). The compose command runs
# `pnpm dev --port 3200 --hostname 0.0.0.0`; source is bind-mounted.
#
# After a dependency change run `make fe-rebuild` (rebuild + renew the
# anonymous node_modules volume, B08 D16); a plain rebuild keeps the stale one.
# A production (standalone) image is part of B13.
FROM node:22-alpine

# pnpm is the project package manager (dev_tools.md). Installed globally and
# pinned so no runtime download/prompt happens as the non-root user.
RUN npm install -g pnpm@9.15.0 && npm cache clean --force

WORKDIR /app

# node_modules and .next are anonymous volumes in docker-compose.yml. Creating
# them here owned by `node` (UID 1000, design D7) makes Docker seed those
# volumes with the right owner instead of root.
RUN mkdir -p /app/node_modules /app/.next && chown -R node:node /app
USER node

COPY --chown=node:node package.json pnpm-lock.yaml* .npmrc ./
RUN pnpm install --frozen-lockfile

COPY --chown=node:node . .

ENV NEXT_TELEMETRY_DISABLED=1
EXPOSE 3200
CMD ["pnpm", "dev", "--port", "3200", "--hostname", "0.0.0.0"]

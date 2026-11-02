# AEGISNOVA Production Deployment Guide

This guide details best practices for containerizing, configuring, and operating AEGISNOVA across production enterprise environments.

---

## 1. Architecture Overview

AEGISNOVA operates as a unified Next.js 14 server with autonomous background workers, evidence ingestion engines, and GitHub integration webhooks:

- **Frontend & Command Center**: Next.js App Router (React 18, Tailwind CSS, Lucide Icons).
- **Autonomous Services**:
  - NightShift SDE Autonomous Patrol (3 AM incident reconciliation & verification).
  - Causal Impact Intelligence & AST static analysis.
  - Independent Repair Assurance engine.
  - Live Evidence Center powered by Tavily Search & CVE reconcilers.
- **REST APIs**: Full OpenAPI-compliant endpoints served under `/api/*`.

---

## 2. Environment Variables Checklist

Configure the following environment variables in `.env.local` or your secret management store:

| Variable | Description | Required | Default |
|---|---|---|---|
| `NODE_ENV` | Runtime environment (`production` or `development`) | Yes | `production` |
| `PORT` | Listening HTTP port | No | `3000` |
| `GITHUB_TOKEN` | GitHub Personal Access Token or App Token for repo audits | Recommended | `""` |
| `TAVILY_API_KEY` | Tavily Search API key for live CVE & patch evidence | Recommended | `""` |
| `NVIDIA_NIM_API_KEY` | NVIDIA NIM endpoint token for LLM reasoning engine | Optional | `""` |
| `NEXT_PUBLIC_BASE_URL` | Canonical domain URL for webhook verification | No | `http://localhost:3000` |

---

## 3. Native Node.js Deployment

### Build & Run
```bash
# Install dependencies
npm ci

# Run verification suite (contracts & smoke tests)
npm test

# Create optimized production build
npm run build

# Start production server
npm start
```

---

## 4. Docker Containerization

### Dockerfile (Multi-stage Build)

```dockerfile
# Stage 1: Build dependencies
FROM node:20-alpine AS deps
WORKDIR /app
COPY package*.json ./
RUN npm ci

# Stage 2: Application builder
FROM node:20-alpine AS builder
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY . .
ENV NODE_ENV=production
RUN npm run build

# Stage 3: Minimal production runner
FROM node:20-alpine AS runner
WORKDIR /app
ENV NODE_ENV=production
ENV PORT=3000

RUN addgroup --system --gid 1001 nodejs
RUN adduser --system --uid 1001 aegisnova

COPY --from=builder /app/public ./public
COPY --from=builder --chown=aegisnova:nodejs /app/.next ./.next
COPY --from=builder /app/node_modules ./node_modules
COPY --from=builder /app/package.json ./package.json

USER aegisnova
EXPOSE 3000
CMD ["npm", "start"]
```

---

## 5. Health Monitoring & Observability

- **API Health**: Query `GET /api/github/status` for connection statuses and API rate limits.
- **Smoke Suite**: Execute `node scripts/test-runner.js` periodically or on deployment trigger.
- **Audit Logs**: Inspect governance traces stored under the security audit trail.

---

## 6. Security Hardening Checklist

1. **Token Scoping**: Grant minimum viable GitHub permissions (`repo`, `pull_requests:write`).
2. **Reverse Proxy**: Place behind TLS termination (Nginx, Traefik, or Cloudflare).
3. **Secret Isolation**: Never commit `.env.local` or raw API credentials to version control.

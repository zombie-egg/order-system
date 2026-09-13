# Builds all three front-ends once, then serves them from a single Nginx
# container that also reverse-proxies the Edge API.
FROM node:24-alpine AS build

WORKDIR /app

COPY package.json package-lock.json ./
COPY apps/kiosk-web/package.json ./apps/kiosk-web/
COPY apps/kitchen-display-web/package.json ./apps/kitchen-display-web/
COPY apps/admin-web/package.json ./apps/admin-web/
COPY packages/contracts/package.json ./packages/contracts/
COPY packages/api-client/package.json ./packages/api-client/
RUN npm ci

COPY tsconfig.base.json ./
COPY packages ./packages
COPY apps/kiosk-web ./apps/kiosk-web
COPY apps/kitchen-display-web ./apps/kitchen-display-web
COPY apps/admin-web ./apps/admin-web

# Every app talks to the API on its own origin, so a relative base URL is all
# that is required. Path prefixes must match the Nginx locations below.
ENV VITE_API_BASE_URL=/api/v1 \
    VITE_API_URL=/api/v1

RUN npm run build --workspace @smart-drink/kiosk-web
RUN npm run build --workspace @smart-drink/kitchen-display-web -- --base=/kds/
RUN npm run build --workspace @smart-drink/admin-web -- --base=/admin/

FROM nginx:1.27-alpine AS runtime

COPY deploy/nginx.conf /etc/nginx/conf.d/default.conf

COPY --from=build /app/apps/kiosk-web/dist/ /usr/share/nginx/html/
COPY --from=build /app/apps/kitchen-display-web/dist/ /usr/share/nginx/html/kds/
COPY --from=build /app/apps/admin-web/dist/ /usr/share/nginx/html/admin/

EXPOSE 80

HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
    CMD ["wget", "--quiet", "--spider", "http://127.0.0.1/healthz"]

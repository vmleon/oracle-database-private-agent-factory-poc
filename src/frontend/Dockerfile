# Build stage: compile the SPA to static assets with Vite.
FROM docker.io/library/node:20-alpine AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
RUN npm run build

# Serve stage: nginx serves the static bundle and reverse-proxies /v1 to the
# backend, so the browser loads the app and calls the API from the same origin
# (no CORS, and SSE streams through nginx).
FROM docker.io/library/nginx:alpine
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80

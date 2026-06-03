# Build stage: compile the SPA to static assets with Vite (base=/backoffice/).
FROM docker.io/library/node:20-alpine AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
RUN npm run build

# Serve stage: nginx serves the static bundle under the /backoffice prefix. The
# proxy front door publishes the public port and routes /backoffice here.
FROM docker.io/library/nginx:alpine
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80

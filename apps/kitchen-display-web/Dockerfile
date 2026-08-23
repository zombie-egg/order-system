FROM node:22-alpine

WORKDIR /app
COPY package.json package-lock.json ./
COPY apps ./apps
COPY packages ./packages

RUN npm ci
RUN npm run build --workspace @smart-drink/kitchen-display-web

ENV HOST=0.0.0.0
EXPOSE 4173

CMD ["sh", "-c", "exec npm run preview --workspace @smart-drink/kitchen-display-web -- --host 0.0.0.0 --port ${PORT:-4173}"]

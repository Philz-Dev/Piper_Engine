FROM node:20-slim

WORKDIR /app

# 1. Copy package files
COPY nexus-ui/package*.json ./nexus-ui/

WORKDIR /app/nexus-ui

# 3. Install
RUN --mount=type=cache,target=/root/.npm \
    npm ci

# 4. Copy ONLY the source code (src, public, next.config.js, etc)
# We avoid copying node_modules by relying on the .dockerignore
COPY nexus-ui/ ./

ENV NODE_ENV=production

# 5. Build
RUN npm run build

EXPOSE 3000
CMD ["npm", "start"]
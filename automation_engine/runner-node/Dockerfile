FROM --platform=linux/amd64 node:18-slim
WORKDIR /app

# Pre-install common automation libraries
RUN npm install axios lodash date-fns

# Copy the runner-node directory into the container
COPY runner-node/ ./runner-node/

# Switch working directory to runner-node so npm install targets package.json correctly
WORKDIR /app/runner-node
RUN npm install --production

ENTRYPOINT ["node", "worker_daemon.js"]
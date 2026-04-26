FROM node:18-slim

WORKDIR /app

# Pre-install common automation libraries
RUN npm install axios lodash date-fns

# Bake the Bridge into the image
COPY runner.js /app/runner.js

ENTRYPOINT ["node", "runner.js"]
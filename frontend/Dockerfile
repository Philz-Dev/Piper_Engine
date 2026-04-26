# 1. Use Node.js as the base
FROM node:20-slim

# 2. Create the working directory
WORKDIR /app

# 3. Copy package files first (for faster builds/caching)
COPY frontend/package*.json ./

# 4. Install JavaScript dependencies
RUN npm install

# 5. Copy the rest of the Nexus UI source code
COPY frontend/ ./frontend/

# 6. Build the app (if you're using React/Vue/Vite)
# Skip this line if it's just a basic Express/Node server
RUN npm run build

# 7. Expose the port (usually 3000 or 5173 for JS apps)
EXPOSE 3000

# 8. Start the frontend
CMD ["npm", "start"]
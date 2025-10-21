# clients/javascript/Dockerfile
FROM node:20-slim

WORKDIR /app

COPY package.json .
RUN npm install --production

COPY client_axios.js client_undici.js ./

# Será especificado qual script rodar via command no docker-compose
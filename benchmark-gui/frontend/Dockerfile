# Build stage
FROM node:18-alpine AS builder

WORKDIR /app

COPY package.json ./

RUN npm install

COPY src ./src
COPY public ./public

RUN npm run build

# Production stage
FROM nginx:alpine

LABEL maintainer="SupremeRAID Developer" \
      description="Frontend for GRAID Benchmarking GUI" \
      version="1.0"

COPY --from=builder /app/build /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 3000

CMD ["nginx", "-g", "daemon off;"]
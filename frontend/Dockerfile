FROM node:20-alpine AS build
WORKDIR /app
COPY package.json ./
RUN npm install
COPY . .
ARG VITE_AI_API_URL
ARG VITE_LIVESHOP_API_URL
ENV VITE_AI_API_URL=$VITE_AI_API_URL
ENV VITE_LIVESHOP_API_URL=$VITE_LIVESHOP_API_URL
RUN npm run build

FROM node:20-alpine
WORKDIR /app
RUN npm install -g serve
COPY --from=build /app/dist ./dist
EXPOSE 80
CMD ["serve", "-s", "dist", "-l", "80"]

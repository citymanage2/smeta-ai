FROM node:20-alpine as build
WORKDIR /app
COPY package*.json ./
RUN npm install
COPY . .
# Vite вшивает VITE_* в бандл на этапе build → пробрасываем URL бэкенда из env панели.
# Не задан → сработает дефолт в client.ts (старый Render). На Timeweb ОБЯЗАТЕЛЬНО задать.
ARG VITE_API_BASE_URL
ENV VITE_API_BASE_URL=$VITE_API_BASE_URL
RUN npm run build

FROM nginx:alpine
COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]

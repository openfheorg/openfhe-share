# docker_stage/frontend.Dockerfile
FROM node:18-bullseye AS build
WORKDIR /app

# Install deps first for better caching
COPY frontend/package*.json ./
RUN npm ci

# Build-time values (compose will pass these)
ARG REACT_APP_API_BASE
ARG REACT_APP_BUILD_FLAVOR=local

# Force the env used by CRA at build time (overrides the repo’s file)
# Also set NEXT_PUBLIC_BACKEND_URL for good measure if the app ever reads it
RUN printf "REACT_APP_API_BASE=%s\nREACT_APP_BUILD_FLAVOR=%s\nNEXT_PUBLIC_BACKEND_URL=%s\n" \
    "$REACT_APP_API_BASE" "$REACT_APP_BUILD_FLAVOR" "$REACT_APP_API_BASE" > .env.production

# Now bring in the source
COPY frontend/ ./

# Build the production bundle
RUN npm run build

FROM node:18-bullseye
WORKDIR /app
COPY --from=build /app/build ./build

RUN npm i -g serve
EXPOSE 3000
CMD ["serve", "-s", "build", "-l", "3000"]

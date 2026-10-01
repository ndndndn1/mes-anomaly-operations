ARG NODE_BUILD_IMAGE=node:22-alpine
ARG JAVA_BUILD_IMAGE=maven:3.9-eclipse-temurin-21
ARG JAVA_RUNTIME_IMAGE=eclipse-temurin:21-jre@sha256:d7051a45dd955e4d5d1db4d3f4269fe13d1c6dff8cc6b7ef89fc8577b96c1982

FROM ${NODE_BUILD_IMAGE} AS web-build
WORKDIR /web
COPY web/package.json web/package-lock.json web/tsconfig.json web/vite.config.ts web/index.html ./
COPY web/src ./src
RUN npm ci --ignore-scripts && npm run build

FROM ${JAVA_BUILD_IMAGE} AS backend-build
ARG MAVEN_PROXY_OPTS=""
WORKDIR /workspace
COPY pom.xml .
COPY src ./src
COPY --from=web-build /web/dist ./src/main/resources/static
RUN MAVEN_OPTS="$MAVEN_PROXY_OPTS" mvn -B test package

FROM backend-build AS test
CMD ["mvn", "-B", "test"]

FROM ${JAVA_RUNTIME_IMAGE} AS runtime
ARG OPENSSL_VERSION=3.5.5-1ubuntu3.6
LABEL org.opencontainers.image.source="https://github.com/ndndndn1/mes-anomaly-operations"
RUN apt-get -o APT::Update::Error-Mode=any update \
    && apt-get install -y --no-install-recommends curl \
        openssl="$OPENSSL_VERSION" libssl3t64="$OPENSSL_VERSION" openssl-provider-legacy="$OPENSSL_VERSION" \
    && groupadd --gid 10001 app \
    && useradd --uid 10001 --gid app --no-create-home --shell /usr/sbin/nologin app \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY --chown=10001:10001 --from=backend-build /workspace/target/mes-anomaly-operations-1.0.0.jar app.jar
USER 10001:10001
CMD ["java", "-jar", "/app/app.jar"]

FROM python:3.13-alpine AS integration-test
WORKDIR /tests
COPY test ./
USER 65534:65534
CMD ["python", "integration.py"]

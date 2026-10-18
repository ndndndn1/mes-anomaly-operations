FROM node:22-alpine AS web-build
WORKDIR /web
COPY web/package.json web/package-lock.json web/tsconfig.json web/vite.config.ts web/index.html ./
COPY web/src ./src
RUN npm ci --ignore-scripts && npm run build

FROM maven:3.9-eclipse-temurin-21 AS backend-build
WORKDIR /workspace
COPY pom.xml .
COPY src ./src
COPY --from=web-build /web/dist ./src/main/resources/static
RUN mvn -B test package

FROM backend-build AS test
CMD ["mvn", "-B", "test"]

FROM eclipse-temurin:21-jre AS runtime
LABEL org.opencontainers.image.source="https://github.com/ndndndn1/mes-anomaly-operations"
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && groupadd --gid 10001 app \
    && useradd --uid 10001 --gid app --no-create-home --shell /usr/sbin/nologin app \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY --chown=10001:10001 --from=backend-build /workspace/target/mes-anomaly-operations-1.0.0.jar app.jar
USER 10001:10001
CMD ["java", "-jar", "/app/app.jar"]

FROM python:3.14-alpine AS integration-test
WORKDIR /tests
COPY test ./
USER 65534:65534
CMD ["python", "integration.py"]

FROM node:22-alpine AS web-build
WORKDIR /web
COPY web/package.json web/tsconfig.json web/vite.config.ts web/index.html ./
COPY web/src ./src
RUN npm install --ignore-scripts && npm run build

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
RUN apt-get update && apt-get install -y --no-install-recommends curl && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY --from=backend-build /workspace/target/mes-anomaly-operations-1.0.0.jar app.jar
CMD ["java", "-jar", "/app/app.jar"]

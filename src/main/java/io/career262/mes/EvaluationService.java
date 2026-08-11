package io.career262.mes;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.SerializationFeature;
import io.micrometer.core.instrument.Counter;
import io.micrometer.core.instrument.MeterRegistry;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.sql.PreparedStatement;
import java.sql.Timestamp;
import java.time.Duration;
import java.util.ArrayList;
import java.util.Collections;
import java.util.HexFormat;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.jdbc.core.BatchPreparedStatementSetter;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.transaction.support.TransactionSynchronization;
import org.springframework.transaction.support.TransactionSynchronizationManager;

@Service
public class EvaluationService {
    private record Measurement(
            String eventId, String lineId, String equipmentId, String sensor,
            java.time.Instant timestamp, double value, RobustDetector.Result result) {}

    private final JdbcTemplate jdbc;
    private final StringRedisTemplate redis;
    private final ObjectMapper mapper;
    private final RequestValidator validator;
    private final RobustDetector detector;
    private final int windowSize;
    private final Duration cacheTtl;
    private final boolean failureInjectionEnabled;
    private final Counter created;
    private final Counter replayed;
    private final Counter cacheFailures;

    public EvaluationService(
            JdbcTemplate jdbc,
            StringRedisTemplate redis,
            ObjectMapper mapper,
            RequestValidator validator,
            MeterRegistry registry,
            @Value("${detector.z-threshold:3.0}") double threshold,
            @Value("${detector.window-size:20}") int windowSize,
            @Value("${detector.cache-ttl:PT24H}") Duration cacheTtl,
            @Value("${test.failure-injection-enabled:false}") boolean failureInjectionEnabled) {
        this.jdbc = jdbc;
        this.redis = redis;
        this.mapper = mapper;
        this.validator = validator;
        this.detector = new RobustDetector(threshold);
        if (windowSize < 5 || windowSize > 1_000) {
            throw new IllegalArgumentException("window size must be between 5 and 1000");
        }
        if (cacheTtl.isZero() || cacheTtl.isNegative() || cacheTtl.compareTo(Duration.ofDays(30)) > 0) {
            throw new IllegalArgumentException("cache TTL must be positive and no more than 30 days");
        }
        this.windowSize = windowSize;
        this.cacheTtl = cacheTtl;
        this.failureInjectionEnabled = failureInjectionEnabled;
        this.created = registry.counter("mes_evaluations_total", "outcome", "created");
        this.replayed = registry.counter("mes_evaluations_total", "outcome", "replayed");
        this.cacheFailures = registry.counter("mes_redis_after_commit_failures_total");
    }

    @Transactional
    public ApiModels.EvaluationResponse evaluate(
            ApiModels.EvaluationRequest request, boolean injectFailure, String requestPath) {
        validator.validate(request);
        String requestHash = hash(request);
        int claimed = jdbc.update(
                "insert into evaluation_event(event_id,line_id,equipment_id,request_hash,request_path) "
                        + "values (?,?,?,?,?) on conflict (event_id) do nothing",
                request.eventId(), request.lineId(), request.equipmentId(), requestHash, requestPath);
        if (claimed == 0) {
            return replay(request.eventId(), requestHash);
        }

        // Serialize evaluations for one equipment. This makes baseline selection and insertion one
        // deterministic PostgreSQL transaction even when callers submit concurrent batches.
        jdbc.query(
                "select pg_advisory_xact_lock(hashtextextended(?, 0))",
                resultSet -> {},
                request.lineId().length() + "|" + request.lineId() + request.equipmentId());

        Map<String, List<Double>> history = new LinkedHashMap<>();
        request.limits().keySet().stream().sorted().forEach(sensor -> {
            List<Double> baseline = new ArrayList<>(jdbc.query(
                        "select value from sensor_sample where line_id=? and equipment_id=? "
                                + "and sensor=? order by observed_at desc,id desc limit ?",
                        (rs, row) -> rs.getDouble(1),
                        request.lineId(), request.equipmentId(), sensor, windowSize));
            Collections.reverse(baseline);
            history.put(sensor, baseline);
        });

        List<Measurement> measurements = new ArrayList<>();
        List<ApiModels.Verdict> verdicts = new ArrayList<>();
        for (ApiModels.Sample sample : request.samples()) {
            sample.values().entrySet().stream().sorted(Map.Entry.comparingByKey()).forEach(entry -> {
                ApiModels.Limits limits = request.limits().get(entry.getKey());
                List<Double> baseline = history.get(entry.getKey());
                RobustDetector.Result result = detector.evaluate(
                        entry.getValue(), baseline, limits.low(), limits.high());
                measurements.add(new Measurement(
                        request.eventId(), request.lineId(), request.equipmentId(), entry.getKey(),
                        sample.timestamp(), entry.getValue(), result));
                verdicts.add(new ApiModels.Verdict(
                        sample.timestamp(), entry.getKey(), entry.getValue(), result.severity(),
                        result.rule(), result.score()));
                baseline.add(entry.getValue());
                if (baseline.size() > windowSize) {
                    baseline.remove(0);
                }
            });
        }

        insertMeasurements(measurements);
        ApiModels.EvaluationResponse response = new ApiModels.EvaluationResponse(
                request.eventId(), request.lineId(), request.equipmentId(), false,
                measurements.size(), List.copyOf(verdicts));

        if (injectFailure && failureInjectionEnabled) {
            throw new IllegalStateException("test failure before commit");
        }
        jdbc.update(
                "update evaluation_event set response_body=?, completed_at=clock_timestamp() where event_id=?",
                toJson(response), request.eventId());
        afterCommit(measurements);
        created.increment();
        return response;
    }

    private ApiModels.EvaluationResponse replay(String eventId, String requestHash) {
        Map<String, Object> event = jdbc.queryForMap(
                "select request_hash,response_body from evaluation_event where event_id=?", eventId);
        if (!requestHash.equals(event.get("request_hash"))) {
            throw new ApiProblemException(
                    409,
                    "Idempotency conflict",
                    "eventId was already used for a different request",
                    Map.of("eventId", "must identify exactly one immutable payload"));
        }
        String body = (String) event.get("response_body");
        if (body == null) {
            throw new IllegalStateException("completed idempotency event has no response");
        }
        try {
            replayed.increment();
            return mapper.readValue(body, ApiModels.EvaluationResponse.class).asReplay();
        } catch (JsonProcessingException exception) {
            throw new IllegalStateException("stored evaluation response is invalid", exception);
        }
    }

    private void insertMeasurements(List<Measurement> measurements) {
        jdbc.batchUpdate(
                "insert into sensor_sample(event_id,line_id,equipment_id,sensor,observed_at,value) "
                        + "values (?,?,?,?,?,?)",
                batch(measurements, false));
        jdbc.batchUpdate(
                "insert into sensor_verdict(event_id,line_id,equipment_id,sensor,observed_at,value,"
                        + "severity,rule_name,score) values (?,?,?,?,?,?,?,?,?)",
                batch(measurements, true));
    }

    private static BatchPreparedStatementSetter batch(
            List<Measurement> measurements, boolean verdict) {
        return new BatchPreparedStatementSetter() {
            @Override
            public void setValues(PreparedStatement statement, int index) throws java.sql.SQLException {
                Measurement value = measurements.get(index);
                statement.setString(1, value.eventId());
                statement.setString(2, value.lineId());
                statement.setString(3, value.equipmentId());
                statement.setString(4, value.sensor());
                statement.setTimestamp(5, Timestamp.from(value.timestamp()));
                statement.setDouble(6, value.value());
                if (verdict) {
                    statement.setString(7, value.result().severity());
                    statement.setString(8, value.result().rule());
                    if (value.result().score() == null) {
                        statement.setNull(9, java.sql.Types.DOUBLE);
                    } else {
                        statement.setDouble(9, value.result().score());
                    }
                }
            }

            @Override
            public int getBatchSize() {
                return measurements.size();
            }
        };
    }

    private void afterCommit(List<Measurement> measurements) {
        List<Measurement> immutable = List.copyOf(measurements);
        TransactionSynchronizationManager.registerSynchronization(new TransactionSynchronization() {
            @Override
            public void afterCommit() {
                try {
                    for (Measurement measurement : immutable) {
                        String key = cacheKey(measurement);
                        redis.opsForList().leftPush(key, Double.toString(measurement.value()));
                        redis.opsForList().trim(key, 0, windowSize - 1);
                        redis.expire(key, cacheTtl);
                    }
                } catch (RuntimeException exception) {
                    // PostgreSQL is authoritative. Cache loss must never turn a committed event into
                    // an HTTP failure that encourages a caller to submit a new event identifier.
                    cacheFailures.increment();
                }
            }
        });
    }

    private static String cacheKey(Measurement value) {
        return "mes:history:" + value.lineId() + ":" + value.equipmentId() + ":" + value.sensor();
    }

    private String hash(ApiModels.EvaluationRequest request) {
        try {
            ObjectMapper canonical = mapper.copy()
                    .configure(SerializationFeature.ORDER_MAP_ENTRIES_BY_KEYS, true);
            byte[] payload = canonical.writeValueAsString(request).getBytes(StandardCharsets.UTF_8);
            return HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(payload));
        } catch (JsonProcessingException | NoSuchAlgorithmException exception) {
            throw new IllegalStateException("cannot hash request", exception);
        }
    }

    private String toJson(ApiModels.EvaluationResponse response) {
        try {
            return mapper.writeValueAsString(response);
        } catch (JsonProcessingException exception) {
            throw new IllegalStateException("cannot persist response", exception);
        }
    }
}

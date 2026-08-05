package io.career262.mes;

import jakarta.validation.Valid;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotEmpty;
import java.sql.Timestamp;
import java.time.Instant;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.http.HttpStatus;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.server.ResponseStatusException;

@RestController
@RequestMapping("/api")
public class JudgeController {
    public record Sample(Instant timestamp, @NotEmpty Map<String, Double> values) {}
    public record Limits(double low, double high) {}
    public record JudgeRequest(@NotBlank String lineId, @NotBlank String equipmentId,
                               Map<String, Limits> limits, @NotEmpty List<@Valid Sample> samples) {}
    public record Verdict(Instant timestamp, String sensor, double value, String severity,
                          String rule, double score) {}
    public record JudgeResponse(String lineId, String equipmentId, int evaluated, List<Verdict> verdicts) {}

    private final StringRedisTemplate redis;
    private final JdbcTemplate jdbc;
    private final RobustDetector detector;
    private final int windowSize;

    public JudgeController(StringRedisTemplate redis, JdbcTemplate jdbc,
                           @Value("${detector.z-threshold:3.0}") double threshold,
                           @Value("${detector.window-size:20}") int windowSize) {
        this.redis = redis;
        this.jdbc = jdbc;
        this.detector = new RobustDetector(threshold);
        this.windowSize = windowSize;
    }

    @PostMapping("/judge")
    public JudgeResponse judge(@Valid @RequestBody JudgeRequest request) {
        List<Sample> ordered = new ArrayList<>(request.samples());
        ordered.sort(Comparator.comparing(Sample::timestamp));
        if (!ordered.equals(request.samples())) {
            throw new ResponseStatusException(HttpStatus.UNPROCESSABLE_ENTITY, "samples must be timestamp ordered");
        }
        List<Verdict> verdicts = new ArrayList<>();
        for (Sample sample : ordered) {
            for (var entry : sample.values().entrySet()) {
                String key = "mes:history:" + request.lineId() + ":" + request.equipmentId() + ":" + entry.getKey();
                List<String> cached = redis.opsForList().range(key, 0, windowSize - 1);
                List<Double> history = cached == null ? List.of() : cached.stream().map(Double::valueOf).toList();
                Limits limits = request.limits().getOrDefault(entry.getKey(), new Limits(-Double.MAX_VALUE, Double.MAX_VALUE));
                RobustDetector.Result result = detector.evaluate(entry.getValue(), history, limits.low(), limits.high());
                Verdict verdict = new Verdict(sample.timestamp(), entry.getKey(), entry.getValue(),
                        result.severity(), result.rule(), result.score());
                verdicts.add(verdict);
                redis.opsForList().leftPush(key, entry.getValue().toString());
                redis.opsForList().trim(key, 0, windowSize - 1);
                jdbc.update("insert into sensor_verdict(line_id,equipment_id,sensor,observed_at,value,severity,rule_name) values (?,?,?,?,?,?,?)",
                        request.lineId(), request.equipmentId(), entry.getKey(), Timestamp.from(sample.timestamp()),
                        entry.getValue(), result.severity(), result.rule());
            }
        }
        return new JudgeResponse(request.lineId(), request.equipmentId(), verdicts.size(), verdicts);
    }

    @PostMapping("/seed")
    public Map<String, Object> seed(@Valid @RequestBody JudgeRequest request) {
        Map<String, Integer> counts = new LinkedHashMap<>();
        for (Sample sample : request.samples()) {
            for (var entry : sample.values().entrySet()) {
                String key = "mes:history:" + request.lineId() + ":" + request.equipmentId() + ":" + entry.getKey();
                redis.opsForList().leftPush(key, entry.getValue().toString());
                redis.opsForList().trim(key, 0, windowSize - 1);
                counts.merge(entry.getKey(), 1, Integer::sum);
            }
        }
        return Map.of("seeded", counts);
    }
}

package io.career262.mes;

import java.time.Clock;
import java.time.Duration;
import java.time.Instant;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.regex.Pattern;
import org.springframework.stereotype.Component;

@Component
final class RequestValidator {
    private static final Pattern SENSOR = Pattern.compile("[A-Za-z][A-Za-z0-9_.:-]{0,79}");
    private static final int MAX_MEASUREMENTS = 10_000;
    private static final Duration MAX_AGE = Duration.ofDays(30);
    private static final Duration MAX_FUTURE = Duration.ofMinutes(5);
    private final Clock clock;

    RequestValidator() {
        this(Clock.systemUTC());
    }

    RequestValidator(Clock clock) {
        this.clock = clock;
    }

    void validate(ApiModels.EvaluationRequest request) {
        Map<String, String> errors = new LinkedHashMap<>();
        Instant now = clock.instant();
        Instant previous = null;
        int measurements = 0;

        for (var entry : request.limits().entrySet()) {
            String path = "limits." + entry.getKey();
            if (!validSensor(entry.getKey())) {
                errors.put(path, "sensor name must match " + SENSOR.pattern());
                continue;
            }
            ApiModels.Limits limits = entry.getValue();
            if (limits == null || limits.low() == null || limits.high() == null) {
                errors.put(path, "low and high are required");
            } else if (!Double.isFinite(limits.low()) || !Double.isFinite(limits.high())) {
                errors.put(path, "limits must be finite numbers");
            } else if (limits.low() >= limits.high()) {
                errors.put(path, "low must be less than high");
            }
        }

        for (int index = 0; index < request.samples().size(); index++) {
            ApiModels.Sample sample = request.samples().get(index);
            if (sample == null || sample.timestamp() == null || sample.values() == null) {
                continue; // Bean Validation reports required fields.
            }
            String path = "samples[" + index + "]";
            if (sample.timestamp().isBefore(now.minus(MAX_AGE))
                    || sample.timestamp().isAfter(now.plus(MAX_FUTURE))) {
                errors.put(path + ".timestamp", "must be within 30 days past and 5 minutes future");
            }
            if (previous != null && !sample.timestamp().isAfter(previous)) {
                errors.put(path + ".timestamp", "timestamps must be strictly increasing");
            }
            previous = sample.timestamp();
            measurements += sample.values().size();
            for (var value : sample.values().entrySet()) {
                String valuePath = path + ".values." + value.getKey();
                if (!validSensor(value.getKey())) {
                    errors.put(valuePath, "sensor name must match " + SENSOR.pattern());
                } else if (!request.limits().containsKey(value.getKey())) {
                    errors.put(valuePath, "a matching limit is required");
                } else if (value.getValue() == null || !Double.isFinite(value.getValue())) {
                    errors.put(valuePath, "value must be a finite number");
                }
            }
        }
        if (measurements > MAX_MEASUREMENTS) {
            errors.put("samples", "batch may contain at most " + MAX_MEASUREMENTS + " measurements");
        }
        if (!errors.isEmpty()) {
            throw new ApiProblemException(422, "Invalid evaluation", "Request invariants failed", errors);
        }
    }

    private static boolean validSensor(String value) {
        return value != null && SENSOR.matcher(value).matches();
    }
}

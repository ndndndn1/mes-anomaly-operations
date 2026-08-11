package io.career262.mes;

import static org.junit.jupiter.api.Assertions.assertDoesNotThrow;
import static org.junit.jupiter.api.Assertions.assertThrows;

import java.time.Clock;
import java.time.Instant;
import java.time.ZoneOffset;
import java.util.List;
import java.util.Map;
import org.junit.jupiter.api.Test;

class RequestValidatorTest {
    private static final Instant NOW = Instant.parse("2026-08-11T00:00:00Z");
    private final RequestValidator validator = new RequestValidator(Clock.fixed(NOW, ZoneOffset.UTC));

    @Test
    void acceptsFiniteOrderedBoundedBatch() {
        assertDoesNotThrow(() -> validator.validate(request(
                List.of(new ApiModels.Sample(NOW, Map.of("temperature", 45.0))))));
    }

    @Test
    void rejectsNonFiniteValuesAndLimits() {
        assertThrows(ApiProblemException.class, () -> validator.validate(new ApiModels.EvaluationRequest(
                "evt-1", "line-1", "press-1",
                Map.of("temperature", new ApiModels.Limits(0.0, Double.POSITIVE_INFINITY)),
                List.of(new ApiModels.Sample(NOW, Map.of("temperature", Double.NaN))))));
    }

    @Test
    void rejectsDuplicateOrReversedTimestamps() {
        assertThrows(ApiProblemException.class, () -> validator.validate(request(List.of(
                new ApiModels.Sample(NOW, Map.of("temperature", 45.0)),
                new ApiModels.Sample(NOW, Map.of("temperature", 46.0))))));
    }

    @Test
    void rejectsUnboundedTimestampAndMissingLimit() {
        assertThrows(ApiProblemException.class, () -> validator.validate(new ApiModels.EvaluationRequest(
                "evt-1", "line-1", "press-1",
                Map.of("temperature", new ApiModels.Limits(0.0, 100.0)),
                List.of(new ApiModels.Sample(
                        NOW.minusSeconds(31L * 24 * 3600), Map.of("vibration", 1.0))))));
    }

    private static ApiModels.EvaluationRequest request(List<ApiModels.Sample> samples) {
        return new ApiModels.EvaluationRequest(
                "evt-1", "line-1", "press-1",
                Map.of("temperature", new ApiModels.Limits(0.0, 100.0)), samples);
    }
}

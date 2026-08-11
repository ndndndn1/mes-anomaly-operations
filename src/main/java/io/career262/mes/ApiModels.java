package io.career262.mes;

import jakarta.validation.Valid;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotEmpty;
import jakarta.validation.constraints.NotNull;
import jakarta.validation.constraints.Pattern;
import jakarta.validation.constraints.Size;
import java.time.Instant;
import java.util.List;
import java.util.Map;

final class ApiModels {
    private static final String ID = "[A-Za-z0-9][A-Za-z0-9._:-]*";

    record Sample(
            @NotNull Instant timestamp,
            @NotEmpty @Size(max = 64) Map<String, @NotNull Double> values) {}

    record Limits(@NotNull Double low, @NotNull Double high) {}

    record EvaluationRequest(
            @NotBlank @Size(max = 80) @Pattern(regexp = ID) String eventId,
            @NotBlank @Size(max = 80) @Pattern(regexp = ID) String lineId,
            @NotBlank @Size(max = 80) @Pattern(regexp = ID) String equipmentId,
            @NotEmpty @Size(max = 64) Map<String, @Valid Limits> limits,
            @NotEmpty @Size(max = 500) List<@Valid Sample> samples) {}

    record Verdict(
            Instant timestamp,
            String sensor,
            double value,
            String severity,
            String rule,
            Double score) {}

    record EvaluationResponse(
            String eventId,
            String lineId,
            String equipmentId,
            boolean replayed,
            int evaluated,
            List<Verdict> verdicts) {
        EvaluationResponse asReplay() {
            return new EvaluationResponse(
                    eventId, lineId, equipmentId, true, evaluated, verdicts);
        }
    }

    private ApiModels() {}
}

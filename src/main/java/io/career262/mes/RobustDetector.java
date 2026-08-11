package io.career262.mes;

import java.util.ArrayList;
import java.util.Collections;
import java.util.List;

public final class RobustDetector {
    public record Result(String severity, String rule, Double score) {}

    private final double threshold;

    public RobustDetector(double threshold) {
        this.threshold = threshold;
    }

    public Result evaluate(double value, List<Double> history, double low, double high) {
        if (value < low || value > high) {
            // JSON has no representation for Infinity. An absolute-limit verdict is categorical,
            // so a statistical score is deliberately absent rather than fabricated.
            return new Result("critical", "absolute_limit", null);
        }
        if (history.size() < 5) {
            return new Result("normal", "insufficient_history", 0.0);
        }
        double median = median(history);
        List<Double> deviations = history.stream().map(v -> Math.abs(v - median)).toList();
        double mad = median(deviations);
        double scale = mad > 1e-9 ? mad * 1.4826 : standardDeviation(history);
        scale = Math.max(scale, 1e-9);
        double score = Math.abs(value - median) / scale;
        if (score >= threshold) {
            return new Result("critical", "robust_z_exceeded", score);
        }
        if (score >= threshold * 0.7) {
            return new Result("warning", "robust_z_warning", score);
        }
        return new Result("normal", "within_band", score);
    }

    private static double median(List<Double> values) {
        List<Double> ordered = new ArrayList<>(values);
        Collections.sort(ordered);
        int middle = ordered.size() / 2;
        return ordered.size() % 2 == 0 ? (ordered.get(middle - 1) + ordered.get(middle)) / 2.0 : ordered.get(middle);
    }

    private static double standardDeviation(List<Double> values) {
        double average = values.stream().mapToDouble(Double::doubleValue).average().orElse(0.0);
        double variance = values.stream().mapToDouble(value -> Math.pow(value - average, 2)).average().orElse(0.0);
        return Math.sqrt(variance);
    }
}

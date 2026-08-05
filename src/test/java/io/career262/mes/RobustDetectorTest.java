package io.career262.mes;

import static org.junit.jupiter.api.Assertions.assertEquals;

import java.util.List;
import org.junit.jupiter.api.Test;

class RobustDetectorTest {
    private final RobustDetector detector = new RobustDetector(3.0);
    private final List<Double> baseline = List.of(45.0, 45.1, 44.9, 45.0, 45.2, 44.8);

    @Test void absoluteLimitWins() {
        assertEquals("absolute_limit", detector.evaluate(92.0, baseline, 10.0, 80.0).rule());
    }

    @Test void distributionOutlierIsDetected() {
        assertEquals("robust_z_exceeded", detector.evaluate(60.0, baseline, 10.0, 80.0).rule());
    }

    @Test void normalValuePasses() {
        assertEquals("normal", detector.evaluate(45.05, baseline, 10.0, 80.0).severity());
    }
}

package io.career262.mes;

import jakarta.servlet.http.HttpServletRequest;
import jakarta.validation.Valid;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RestController;

/** HTTP adapter. The legacy path intentionally delegates to the versioned contract. */
@RestController
public class JudgeController {
    private final EvaluationService service;

    public JudgeController(EvaluationService service) {
        this.service = service;
    }

    @PostMapping({"/api/v1/evaluations", "/api/judge"})
    public ResponseEntity<ApiModels.EvaluationResponse> evaluate(
            @Valid @RequestBody ApiModels.EvaluationRequest request,
            @RequestHeader(value = "X-Test-Fail-Before-Commit", required = false) String failHeader,
            HttpServletRequest httpRequest) {
        ApiModels.EvaluationResponse response = service.evaluate(
                request, "true".equalsIgnoreCase(failHeader), httpRequest.getRequestURI());
        return ResponseEntity.status(response.replayed() ? HttpStatus.OK : HttpStatus.CREATED)
                .body(response);
    }
}

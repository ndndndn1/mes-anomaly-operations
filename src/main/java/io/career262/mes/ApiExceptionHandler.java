package io.career262.mes;

import jakarta.servlet.http.HttpServletRequest;
import java.net.URI;
import java.util.LinkedHashMap;
import java.util.Map;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.slf4j.MDC;
import org.springframework.http.HttpStatus;
import org.springframework.http.HttpStatusCode;
import org.springframework.http.ProblemDetail;
import org.springframework.http.ResponseEntity;
import org.springframework.http.converter.HttpMessageNotReadableException;
import org.springframework.validation.FieldError;
import org.springframework.web.bind.MethodArgumentNotValidException;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.RestControllerAdvice;

@RestControllerAdvice
final class ApiExceptionHandler {
    private static final Logger LOGGER = LoggerFactory.getLogger(ApiExceptionHandler.class);
    @ExceptionHandler(ApiProblemException.class)
    ResponseEntity<ProblemDetail> apiProblem(ApiProblemException exception, HttpServletRequest request) {
        ProblemDetail problem = problem(
                exception.status(), exception.title(), exception.getMessage(), request);
        problem.setProperty("errors", exception.errors());
        return ResponseEntity.status(exception.status()).body(problem);
    }

    @ExceptionHandler(MethodArgumentNotValidException.class)
    ResponseEntity<ProblemDetail> beanValidation(
            MethodArgumentNotValidException exception, HttpServletRequest request) {
        Map<String, String> errors = new LinkedHashMap<>();
        exception.getBindingResult().getAllErrors().forEach(error -> {
            String path = error instanceof FieldError field ? field.getField() : error.getObjectName();
            errors.putIfAbsent(path, error.getDefaultMessage());
        });
        ProblemDetail problem = problem(
                422, "Invalid evaluation", "Request validation failed", request);
        problem.setProperty("errors", errors);
        return ResponseEntity.unprocessableEntity().body(problem);
    }

    @ExceptionHandler(HttpMessageNotReadableException.class)
    ResponseEntity<ProblemDetail> malformedJson(
            HttpMessageNotReadableException exception, HttpServletRequest request) {
        return ResponseEntity.badRequest().body(problem(
                400, "Malformed JSON", "Request body is not valid JSON for this endpoint", request));
    }

    @ExceptionHandler(Exception.class)
    ResponseEntity<ProblemDetail> internal(Exception exception, HttpServletRequest request) {
        LOGGER.error("request failed", exception);
        return ResponseEntity.status(HttpStatus.INTERNAL_SERVER_ERROR).body(problem(
                500, "Internal server error", "The evaluation could not be completed", request));
    }

    private static ProblemDetail problem(
            int status, String title, String detail, HttpServletRequest request) {
        ProblemDetail problem = ProblemDetail.forStatusAndDetail(HttpStatusCode.valueOf(status), detail);
        problem.setTitle(title);
        problem.setType(URI.create("https://github.com/ndndndn1/mes-anomaly-operations/problems/"
                + title.toLowerCase().replace(' ', '-')));
        problem.setInstance(URI.create(request.getRequestURI()));
        problem.setProperty("requestId", MDC.get(RequestIdFilter.MDC_KEY));
        return problem;
    }
}

package io.career262.mes;

import java.util.Map;

final class ApiProblemException extends RuntimeException {
    private final int status;
    private final String title;
    private final Map<String, String> errors;

    ApiProblemException(int status, String title, String detail, Map<String, String> errors) {
        super(detail);
        this.status = status;
        this.title = title;
        this.errors = Map.copyOf(errors);
    }

    int status() { return status; }
    String title() { return title; }
    Map<String, String> errors() { return errors; }
}

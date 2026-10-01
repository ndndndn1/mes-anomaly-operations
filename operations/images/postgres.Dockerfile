FROM postgres:17-alpine@sha256:b0f9560a2de083e2cc7382e75f808c7381a32852a7ec49117deedb300e552b24
# The controller always starts postgres directly as this user. Root privilege
# switching is unsupported and its unused Go binary is removed, not suppressed.
USER root
RUN rm /usr/local/bin/gosu
USER postgres

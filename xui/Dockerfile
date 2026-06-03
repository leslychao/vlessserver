ARG XUI_IMAGE=ghcr.io/mhsanaei/3x-ui:v2.9.0
FROM ${XUI_IMAGE}

USER root

COPY xui/entrypoint.sh /usr/local/bin/proxy-stack-xui-entrypoint
RUN chmod 0755 /usr/local/bin/proxy-stack-xui-entrypoint

ENTRYPOINT ["/usr/local/bin/proxy-stack-xui-entrypoint"]


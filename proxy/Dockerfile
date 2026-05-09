# Default proxy flavour: stays exactly on the upstream CRS image.
# WHY: this Dockerfile is what the docker-compose ${PROXY_FLAVOR_DOCKERFILE}
#      switch points to by default. Switching to Dockerfile.openresty is opt-in
#      (this release, ADR-0010) for environments that want Lua subrequest scoring.
FROM owasp/modsecurity-crs:nginx-alpine

# Security policy

## Supported versions

Security fixes go into the latest release of Hydrograf and into the development branch
`develop`. Older releases are not patched.

## Reporting a vulnerability

Please do not report vulnerabilities in public issues or pull requests.

Use GitHub's private vulnerability reporting: open the **Security** tab of
<https://github.com/Daldek/Hydrograf>, choose **Report a vulnerability** and describe the
problem, the affected version and, if possible, how to reproduce it. You get an answer as
soon as the maintainer can read the report; a fix is released as a patch version and
credited in the CHANGELOG unless you prefer otherwise.

## Scope

Hydrograf is a web service: a FastAPI application with a PostGIS database behind nginx
(Docker Compose), a public map and analysis interface without accounts, and an admin
panel protected by an API key. Reports about the authentication of the admin panel, SQL
injection or missing validation in the endpoints, requests that exhaust the service
(unbounded delineation areas, tiles, uploads), the handling of uploaded files (sewer
network data), secrets or internal paths in responses and logs, the container, nginx and
Compose configuration, or the supply chain of the application are in scope. The producers
(Hydrolog, Kartograf, IMGWTools) and the third-party libraries have their own policies;
report their defects to them.

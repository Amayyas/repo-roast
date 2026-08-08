# Two stages so the final image never carries pip, setuptools, or a build
# toolchain -- only the installed package and its runtime dependencies.
FROM python:3.12-slim-bookworm AS builder

WORKDIR /src
COPY pyproject.toml README.md LICENSE ./
COPY src ./src

# --prefix, not a venv: installs straight into a tree that gets copied whole
# into the final stage's /usr/local, no activation script needed at runtime.
RUN pip install --no-cache-dir --prefix=/install .

FROM python:3.12-slim-bookworm

# No -m/--create-home: a stateless CLI has nothing to keep in a home directory.
# --system keeps it out of /etc/passwd's human-user range.
RUN useradd --system --no-create-home --shell /usr/sbin/nologin roast \
    # The base image ships pip; the installed package's console_script does
    # not need it at runtime, and an installer is exactly the kind of tool
    # that has no business surviving into the final layer.
    && rm -rf /usr/local/lib/python3.12/site-packages/pip* \
              /usr/local/bin/pip /usr/local/bin/pip3

COPY --from=builder /install /usr/local

USER roast
ENTRYPOINT ["repo-roast"]

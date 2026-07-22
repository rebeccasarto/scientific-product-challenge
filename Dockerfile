FROM python:3.9-slim

WORKDIR /app

ARG QUARTO_VERSION=1.9.38

COPY requirements.txt ./
RUN apt-get update \
    && apt-get install --no-install-recommends -y ca-certificates curl \
    && curl --fail --location --output /tmp/quarto.deb \
      "https://github.com/quarto-dev/quarto-cli/releases/download/v${QUARTO_VERSION}/quarto-${QUARTO_VERSION}-linux-amd64.deb" \
    && apt-get install -y /tmp/quarto.deb \
    && rm -rf /var/lib/apt/lists/* /tmp/quarto.deb \
    && pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8000

CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]

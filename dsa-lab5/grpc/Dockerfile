FROM python:3.9-slim

WORKDIR /DSA-LAB5/grpc

COPY requirements.txt .


RUN pip install --no-cache-dir -r requirements.txt


COPY . .

EXPOSE 50051

# For Alpine-based images (if you're using python:3.9-alpine etc.)
RUN apk add --no-cache wget || \
    (apt-get update && apt-get install -y wget) || \
    (yum install -y wget) && \
    GRPC_HEALTH_PROBE_VERSION=v0.4.24 && \
    wget -qO/bin/grpc_health_probe https://github.com/grpc-ecosystem/grpc-health-probe/releases/download/${GRPC_HEALTH_PROBE_VERSION}/grpc_health_probe-linux-amd64 && \
    chmod +x /bin/grpc_health_probe

CMD [ "python", "server.py" ]
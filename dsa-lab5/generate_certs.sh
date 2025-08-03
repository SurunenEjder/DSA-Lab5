#!/bin/bash
set -e

echo "Generating certificates for mutual TLS with proper hostnames..."

# Clean up any existing files
rm -rf ca.key ca.crt grpc-service.key grpc-service.crt rest-service.key rest-service.crt *.csr *.srl

# Create CA key and certificate
openssl genrsa -out ca.key 4096
openssl req -new -x509 -key ca.key -sha256 -subj "/C=US/ST=CA/O=DSA-LAB/CN=CA" -days 365 -out ca.crt

# Create config file for gRPC service with multiple hostnames
cat > grpc-service.conf << 'CONF'
[req]
distinguished_name = req_distinguished_name
req_extensions = v3_req
prompt = no

[req_distinguished_name]
C = US
ST = CA
O = DSA-LAB
CN = grpc-service

[v3_req]
keyUsage = keyEncipherment, dataEncipherment
extendedKeyUsage = serverAuth, clientAuth
subjectAltName = @alt_names

[alt_names]
DNS.1 = grpc-service
DNS.2 = localhost
IP.1 = 127.0.0.1
CONF

# Create gRPC service key and certificate with SAN
openssl genrsa -out grpc-service.key 4096
openssl req -new -key grpc-service.key -out grpc-service.csr -config grpc-service.conf
openssl x509 -req -in grpc-service.csr -CA ca.crt -CAkey ca.key -CAcreateserial \
    -out grpc-service.crt -days 365 -sha256 -extensions v3_req -extfile grpc-service.conf

# Create config file for REST service
cat > rest-service.conf << 'CONF'
[req]
distinguished_name = req_distinguished_name
req_extensions = v3_req
prompt = no

[req_distinguished_name]
C = US
ST = CA
O = DSA-LAB
CN = rest-service

[v3_req]
keyUsage = keyEncipherment, dataEncipherment
extendedKeyUsage = serverAuth, clientAuth
subjectAltName = @alt_names

[alt_names]
DNS.1 = rest-service
DNS.2 = localhost
IP.1 = 127.0.0.1
CONF

# Create REST service key and certificate with SAN
openssl genrsa -out rest-service.key 4096
openssl req -new -key rest-service.key -out rest-service.csr -config rest-service.conf
openssl x509 -req -in rest-service.csr -CA ca.crt -CAkey ca.key -CAcreateserial \
    -out rest-service.crt -days 365 -sha256 -extensions v3_req -extfile rest-service.conf

# Cleanup
rm -f *.csr *.srl *.conf

# Set proper permissions
chmod 644 *.crt *.key

echo "Certificates with Subject Alternative Names generated successfully!"
ls -la *.crt *.key

# Verify certificate details
echo "=== Certificate verification ==="
openssl x509 -in grpc-service.crt -text -noout | grep -A 5 "Subject Alternative Name" || echo "No SAN found"

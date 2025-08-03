# DSA Lab 5 - Secure Microservices with Flask REST API and gRPC

A distributed system architecture implementing a secure Flask REST API that communicates with a gRPC backend service, featuring JWT authentication, mutual TLS, circuit breakers, and comprehensive monitoring.

## 🏗️ Architecture Overview

![Baseline Architecture](architecture-diagram.png)

### Architecture Components

```
Browser (User) ──TLS──→ Traefik Gateway ──HTTP──→ REST Service
                           (HTTPS)                    │
                                                      │
Keycloak (OIDC) ←──────── JWT/JWKS ──────────────────┘
     │                                                │
     │                                               mTLS
     │                                                │
     └─ JWT Token Validation                          ▼
                                              gRPC Service ──TCP──→ MongoDB
                                                      │
                                                      │
                                              Prometheus ←─ Metrics
                                                      │
                                                      ▼
                                                  Grafana
```

### Security Layers

| Layer | Protocol | Purpose |
|-------|----------|---------|
| **Browser → Traefik** | TLS (HTTPS) | Encrypt external traffic |
| **Traefik → REST** | HTTP | Internal network communication |
| **REST → gRPC** | mTLS | Mutual authentication & encryption |
| **Authentication** | JWT/OIDC | Token-based access control |
| **Monitoring** | HTTP | Metrics collection |

## 🚀 Features

### Security Architecture
- **TLS Termination** at Traefik Gateway (Port 443)
- **JWT Authentication** with Keycloak OIDC integration
- **Mutual TLS (mTLS)** for REST ↔ gRPC communication
- **Certificate-based authentication** between services
- **Token validation** and expiration handling

### Resilience Patterns
- **Circuit Breaker Pattern** for gRPC fault tolerance
- **Retry Logic** with exponential backoff
- **Health Check Endpoints** for service monitoring
- **Graceful error handling** and recovery

### Observability Stack
- **Prometheus Metrics** collection from all services
- **Grafana Dashboards** for real-time visualization
- **Custom metrics** for API performance tracking
- **Service health monitoring** and alerting

### Development Experience
- **Docker Compose** orchestration for easy deployment
- **Hot reload** in development mode
- **Comprehensive logging** across all services
- **API documentation** and testing tools

## 📋 Prerequisites

- Docker and Docker Compose
- Python 3.9+
- OpenSSL (for certificate generation)
- curl (for testing)
- jq (for JSON parsing)

## 🛠️ Installation & Setup

### 1. Clone the Repository
```bash
git clone <repository-url>
cd dsa-lab5
```

### 2. Generate Security Certificates
```bash
# Make the script executable
chmod +x generate_certs.sh

# Generate certificates for mutual TLS
./generate_certs.sh
```

This creates:
- `ca.crt` - Certificate Authority
- `rest-service.crt/key` - REST service certificates
- `grpc-service.crt/key` - gRPC service certificates

### 3. Start the Complete Stack
```bash
# Start all services
docker compose up -d

# Check service status
docker compose ps
```

### 4. Verify TLS Setup
```bash
# Test HTTPS endpoint (TLS termination at Traefik)
curl -k https://localhost:443/health

# Test internal health check
curl http://localhost:5000/health

# Should return:
# {"status":"healthy","grpc":"connected","authentication":"enabled","breaker":"closed"}
```

## 🔐 Security Configuration

### TLS Configuration

**Traefik Gateway (TLS Termination):**
```yaml
entryPoints:
  websecure:
    address: ":443"

tls:
  certificates:
    - certFile: "/certs/rest-service.crt"
      keyFile: "/certs/rest-service.key"
```

**gRPC Service (mTLS):**
```python
# Mutual TLS for gRPC communication
credentials = grpc.ssl_channel_credentials(
    root_certificates=ca_cert,
    private_key=client_key,
    certificate_chain=client_cert
)
```

### Authentication Flow

1. **User** requests access via browser (HTTPS)
2. **Traefik** terminates TLS and forwards to REST service
3. **REST Service** validates JWT token with Keycloak
4. **Authorized requests** proceed to gRPC service via mTLS
5. **gRPC Service** processes request and returns data

## 📚 API Endpoints

### Authentication
| Method | Endpoint | Description | Protocol |
|--------|----------|-------------|----------|
| POST | `/auth` | Get JWT token | HTTPS |
| POST | `/auth/expired` | Get expired token (testing) | HTTPS |

### Items Management (Protected)
| Method | Endpoint | Description | Auth Required | Protocol |
|--------|----------|-------------|---------------|----------|
| GET | `/items` | List all items | ✅ JWT | HTTPS |
| POST | `/items` | Create item | ✅ JWT | HTTPS |
| GET | `/items/{id}` | Get item by ID | ✅ JWT | HTTPS |
| PUT | `/items/{id}` | Update item | ✅ JWT | HTTPS |
| DELETE | `/items/{id}` | Delete item | ✅ JWT | HTTPS |

### System Endpoints
| Method | Endpoint | Description | Protocol |
|--------|----------|-------------|----------|
| GET | `/health` | Health check | HTTP/HTTPS |
| GET | `/metrics` | Prometheus metrics | HTTP |
| POST | `/reset-breaker` | Reset circuit breaker | HTTP |

## 🔧 Service Configuration

### Port Mapping
| Service | Internal Port | External Port | Protocol |
|---------|---------------|---------------|----------|
| **Traefik Gateway** | 443 | 443 | HTTPS |
| **REST API** | 5000 | 5000 | HTTP |
| **gRPC Service** | 50051 | - | mTLS |
| **MongoDB** | 27017 | 27017 | TCP |
| **Keycloak** | 8080 | 8080 | HTTP |
| **Prometheus** | 9090 | 9090 | HTTP |
| **Grafana** | 3000 | 3000 | HTTP |

### Environment Variables

**Flask REST API:**
```env
GRPC_HOST=grpc-service
GRPC_PORT=50051
SECRET_KEY=your-secret-key
KEYCLOAK_URL=http://keycloak:8080
```

**gRPC Service:**
```env
MONGO_HOST=mymongo
MONGO_PORT=27017
MONGO_PASSWORD=example
```

## 🧪 Security Testing

### 1. TLS/HTTPS Testing
```bash
# Test HTTPS connection to Traefik
curl -k -v https://localhost:443/health

# Check certificate details
openssl s_client -connect localhost:443 -servername localhost

# Test certificate validation
curl https://localhost:443/health  # Should show cert error without -k
```

### 2. Authentication Security Tests

#### Missing Token (401 Expected)
```bash
curl -v https://localhost:443/items
# Expected: {"error":"Missing authorization header"}
# HTTP Status: 401 UNAUTHORIZED
```

#### Invalid Token (401 Expected)
```bash
curl -H "Authorization: Bearer invalid-token" https://localhost:443/items
# Expected: {"error":"Invalid token"}
# HTTP Status: 401 UNAUTHORIZED
```

#### Expired Token (401 Expected)
```bash
# Generate expired token
EXPIRED_TOKEN=$(curl -s -X POST https://localhost:443/auth/expired \
  -k -H "Content-Type: application/json" \
  -d '{"username": "admin"}' | jq -r '.expired_token')

# Test with expired token
curl -k -H "Authorization: Bearer $EXPIRED_TOKEN" https://localhost:443/items
# Expected: {"error":"Token has expired"}
# HTTP Status: 401 UNAUTHORIZED
```

### 3. Mutual TLS Testing

#### Valid Certificate Test
```bash
# Get valid token
TOKEN=$(curl -s -X POST https://localhost:443/auth \
  -k -H "Content-Type: application/json" \
  -d '{"username": "admin", "password": "secret"}' | jq -r '.token')

# Test with valid token (should work)
curl -k -H "Authorization: Bearer $TOKEN" https://localhost:443/items
```

#### Wrong Certificate Test
```bash
# Stop services
docker compose down

# Corrupt certificates to test mTLS
echo "INVALID_CERT" > rest-service.crt
echo "INVALID_KEY" > rest-service.key

# Start services and test
docker compose up -d

# Test - should fail due to certificate mismatch
TOKEN=$(curl -s -X POST https://localhost:443/auth \
  -k -H "Content-Type: application/json" \
  -d '{"username": "admin", "password": "secret"}' | jq -r '.token')

curl -k -H "Authorization: Bearer $TOKEN" https://localhost:443/items
# Expected: {"error":"Service error"} - gRPC connection fails
```

### 4. Network Security Testing

#### Packet Sniffing Test
```bash
# Monitor HTTPS traffic (should be encrypted)
sudo tcpdump -i lo port 443 -A -s 0

# In another terminal, make request
curl -k -H "Authorization: Bearer $TOKEN" https://localhost:443/items
# Expected: Encrypted traffic (unreadable payload)
```

#### Man-in-the-Middle Protection
```bash
# Test certificate pinning/validation
curl https://localhost:443/health  # Without -k flag
# Expected: SSL certificate verification error
```

## 📊 Monitoring & Observability

### Prometheus Metrics
Access: http://localhost:9090

**Key Metrics:**
- `flask_http_request_total` - API request counts
- `grpc_connection_status` - gRPC health status
- `circuit_breaker_state` - Circuit breaker status
- `tls_handshake_duration` - TLS performance

### Grafana Dashboards
Access: http://localhost:3000
- Username: `admin`
- Password: `admin`

**Dashboards:**
- Service Health Overview
- API Performance Metrics
- Security Event Monitoring
- TLS Connection Status

## 🛡️ Security Threat Simulation Results

| Threat Type | Test Scenario | Expected Result | Status |
|-------------|---------------|-----------------|--------|
| **Authentication Bypass** | Missing JWT token | 401 Unauthorized | ✅ PASSED |
| **Token Manipulation** | Invalid JWT signature | 401 Unauthorized | ✅ PASSED |
| **Session Hijacking** | Expired JWT token | 401 Unauthorized | ✅ PASSED |
| **Certificate Spoofing** | Wrong mTLS certificate | Connection rejected | ✅ PASSED |
| **Network Eavesdropping** | Packet sniffing HTTPS | Encrypted payload | ✅ PASSED |

## 🐛 Troubleshooting

### TLS/Certificate Issues
```bash
# Check certificate files exist
ls -la *.crt *.key

# Verify certificate validity
openssl x509 -in rest-service.crt -text -noout

# Test certificate chain
openssl verify -CAfile ca.crt rest-service.crt
```

### gRPC Connection Issues
```bash
# Check gRPC service logs
docker logs grpc-service

# Test gRPC health directly
grpc_health_probe -addr=localhost:50051

# Verify mTLS certificates
openssl s_client -connect localhost:50051 -cert rest-service.crt -key rest-service.key
```

### Authentication Problems
```bash
# Check Keycloak connectivity
curl http://localhost:8080/realms/dsa-lab/.well-known/openid_configuration

# Verify JWT secret configuration
docker logs rest-service | grep "SECRET_KEY"

# Test token generation
curl -X POST https://localhost:443/auth \
  -k -H "Content-Type: application/json" \
  -d '{"username": "admin", "password": "secret"}'
```

## 📁 Project Structure

```
dsa-lab5/
├── rest/
│   ├── app.py              # Flask REST API with TLS
│   ├── jwt_middleware.py   # JWT validation logic
│   ├── Dockerfile          # REST service container
│   └── requirements.txt    # Python dependencies
├── grpc/
│   ├── server.py           # gRPC service with mTLS
│   ├── items_pb2.py        # Protobuf definitions
│   ├── Dockerfile          # gRPC service container
│   └── requirements.txt    # Python dependencies
├── security/
│   ├── traefik.yml         # TLS termination config
│   ├── keycloak/
│   │   └── realm-export.json # OIDC configuration
│   └── certs/              # Certificate directory
├── monitoring/
│   ├── prometheus.yml      # Metrics configuration
│   └── grafana/           # Dashboard definitions
├── docker-compose.yml      # Service orchestration
├── generate_certs.sh       # Certificate generation script
├── architecture-diagram.png # System architecture
└── README.md              # This file
```

## 🔒 Security Implementation Summary

### Implemented Security Controls
- [x] **TLS Encryption** (Browser ↔ Traefik)
- [x] **Mutual TLS** (REST ↔ gRPC)
- [x] **JWT Authentication** (Keycloak OIDC)
- [x] **Certificate Validation** (mTLS handshake)
- [x] **Token Expiration** (Time-based security)
- [x] **Input Validation** (API parameter checking)
- [x] **Error Handling** (Secure error responses)
- [x] **Security Headers** (HTTP security headers)

### Security Architecture Benefits
- **Defense in Depth**: Multiple security layers
- **Zero Trust**: Mutual authentication required
- **Encryption Everywhere**: TLS for external, mTLS for internal
- **Observable Security**: Metrics and monitoring
- **Testable Security**: Comprehensive threat simulation

## 📄 License

This project is created for educational purposes as part of DSA Lab assignments.

## 👥 Contributors

- [Your Name] - Architecture Design and Implementation
- [Your Team] - Security Testing and Documentation

---

**🔒 Security Note**: This implementation demonstrates enterprise-grade security patterns including TLS termination, mutual TLS, and comprehensive authentication. All certificates are self-signed for lab purposes - use proper CA-signed certificates in production.

For questions or issues, please refer to the troubleshooting section or check the service logs using `docker logs <service-name>`.

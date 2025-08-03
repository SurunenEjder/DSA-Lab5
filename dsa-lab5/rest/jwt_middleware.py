import requests
import jose.jwt
from jose import jwk
from flask import request, abort, g
from jose import JWTError

# Global constants set at startup (see Step 4.2)
KEYS = None  # dict(kid -> JWK dict)
ISS = "http://localhost:8080/realms/dsa-lab"  # Changed from keycloak to localhost
AUD = "rest-client"

def fetch_jwks():
    """Fetch Keycloak's JWKS once at startup"""
    global KEYS
    JWKS_URL = "http://keycloak:8080/realms/dsa-lab/protocol/openid-connect/certs"  # Keep keycloak for internal access
    response = requests.get(JWKS_URL)
    keys_data = response.json()
    KEYS = {k["kid"]: k for k in keys_data["keys"]}
    print(f"Fetched {len(KEYS)} keys from Keycloak JWKS")

def verify_token():
    """Validates before each request - stops the request with 401 if the bearer token is missing / expired / has wrong audience / bad sig."""
    
    # Check for Authorization header
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        abort(401, description="missing Bearer token")
    
    token = auth.removeprefix("Bearer ").strip()
    
    try:
        # 1) read unverified header to find the key ID (kid)
        header = jose.jwt.get_unverified_header(token)
        if "kid" not in header:
            abort(401, description="invalid header: missing kid")
        
        kid = header.get("kid")
        if kid not in KEYS:
            abort(401, description="unknown kid")
        
        # 2) Use the JWK directly with python-jose (CORRECT METHOD)
        jwk_dict = KEYS[kid]
        
        # 3) verify signature + standard claims
        claims = jose.jwt.decode(
            token,
            jwk_dict,
            algorithms=[header["alg"]],
            audience=AUD,
            issuer=ISS,
        )
        
        # 4) make the user identity available to downstream code
        g.user = claims.get("preferred_username", claims.get("sub"))
        g.claims = claims
        
    except JWTError as exc:
        abort(401, description=f"invalid token: {exc}")
    except Exception as exc:
        abort(401, description=f"token validation error: {exc}")
import jwt, json, sys
if len(sys.argv) < 2:
    print("Usage: python decodeJWT.py")
    sys.exit(1)
    
token = sys.argv[1]

# Decode without verifying signature
header = jwt.get_unverified_header(token)
claims = jwt.decode(token, options={"verify_signature": False})

print("\n=== HEADER ===")
print(json.dumps(header, indent=2))
print("\n=== CLAIMS ===")
print(json.dumps(claims, indent=2))
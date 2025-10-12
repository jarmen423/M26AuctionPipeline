#!/usr/bin/env python3
"""Extract and validate auth payload samples from Frida capture."""
import json
from pathlib import Path
from collections import defaultdict

def main():
    captures_dir = Path(r"C:\Users\jfrie\Documents\Projects\captures")
    input_file = captures_dir / "auth_payloads.jsonl"
    output_file = captures_dir / "auth_samples_clean.jsonl"
    
    # Track payload sets (group by timestamp proximity)
    valid_sets = []
    current_set = {}
    last_ts = 0
    
    with open(input_file, 'r', encoding='utf-8') as f:
        for line in f:
            try:
                entry = json.loads(line.strip())
                tag = entry.get('tag')
                ts = entry.get('ts', 0)
                
                # Reset set if timestamp gap > 1 second
                if ts - last_ts > 1000:
                    if current_set.get('setAuthData') and current_set.get('setAuthCode'):
                        valid_sets.append(current_set)
                    current_set = {'ts': ts}
                
                last_ts = ts
                
                # Collect relevant entries
                if tag == 'authPayload':
                    hex_data = entry.get('buffer', {}).get('hex', '')
                    if hex_data and len(hex_data) > 100:  # Valid data
                        current_set['authPayload'] = entry
                        
                elif tag == 'setAuthData':
                    hex_data = entry.get('hex', '')
                    if hex_data and len(hex_data) == 142:  # 71 bytes = 142 hex chars
                        current_set['setAuthData'] = entry
                        
                elif tag == 'setAuthCode':
                    hex_data = entry.get('hex', '')
                    if hex_data and len(hex_data) == 32:  # 16 bytes = 32 hex chars
                        current_set['setAuthCode'] = entry
                        
                elif tag == 'getAuthCode':
                    hex_data = entry.get('hex', '')
                    if hex_data and len(hex_data) > 0:
                        current_set['getAuthCode'] = entry
                        
            except json.JSONDecodeError:
                continue
    
    # Add last set
    if current_set.get('setAuthData') and current_set.get('setAuthCode'):
        valid_sets.append(current_set)
    
    print(f"✅ Found {len(valid_sets)} complete auth payload sets")
    
    # Write clean samples
    with open(output_file, 'w', encoding='utf-8') as f:
        for i, payload_set in enumerate(valid_sets[:10], 1):  # First 10 samples
            f.write(json.dumps(payload_set, separators=(',', ':')) + '\n')
            
            # Print summary
            auth_data_hex = payload_set['setAuthData']['hex']
            auth_code_hex = payload_set['setAuthCode']['hex']
            
            # Decode nonce from authPayload
            auth_payload_hex = payload_set.get('authPayload', {}).get('buffer', {}).get('hex', '')
            if auth_payload_hex:
                # First 4 bytes are the nonce
                nonce_hex = auth_payload_hex[:8]
                print(f"\nSample {i}:")
                print(f"  Nonce: {nonce_hex}")
                print(f"  AuthData (71 bytes): {auth_data_hex[:40]}...")
                print(f"  AuthCode (16 bytes): {auth_code_hex}")
    
    print(f"\n✅ Wrote clean samples to: {output_file}")
    
    # Parse one sample to show JSON payload
    if valid_sets:
        sample = valid_sets[0]
        auth_payload_hex = sample.get('authPayload', {}).get('buffer', {}).get('hex', '')
        if auth_payload_hex:
            # Extract JSON (starts after 4-byte nonce)
            try:
                # Find the JSON start (7b = '{')
                json_start = auth_payload_hex.index('7b')
                json_hex = auth_payload_hex[json_start:]
                # Find null terminator (00)
                json_end = json_hex.index('00')
                json_hex = json_hex[:json_end]
                
                # Decode hex to string
                json_bytes = bytes.fromhex(json_hex)
                json_str = json_bytes.decode('utf-8')
                json_data = json.loads(json_str)
                
                print(f"\n📦 Decoded JSON Payload:")
                print(f"  staticData: {json_data.get('staticData')}")
                print(f"  requestId: {json_data.get('requestId')}")
                print(f"  blazeId: {json_data.get('blazeId')}")
            except (ValueError, UnicodeDecodeError, json.JSONDecodeError) as e:
                print(f"⚠️ Could not decode JSON: {e}")

if __name__ == '__main__':
    main()

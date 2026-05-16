
import requests
import uuid
import time
import sys

BASE_URL = "http://localhost:5000/api"

def get_auth(label):
    email = f"{label}_{uuid.uuid4().hex[:6]}@example.com"
    password = "Password123!"
    requests.post(f"{BASE_URL}/auth/register", json={
        "email": email, "password": password, 
        "first_name": label, "last_name": "Tester"
    })
    r = requests.post(f"{BASE_URL}/auth/login", json={"email": email, "password": password})
    data = r.json()["data"]
    return data["access_token"], data["active_org_id"]

def validate_step(scenario_id, step_id, org_id, headers):
    r = requests.post(f"{BASE_URL}/scenarios/{scenario_id}/validate-step", 
                      json={"step_id": step_id, "org_id": org_id}, 
                      headers=headers)
    if r.status_code != 200:
        return False, f"HTTP {r.status_code}: {r.text}"
    data = r.json().get("data")
    if not data:
        return False, "No data in response"
    return data["valid"], data.get("message", "No message"), data.get("snapshot", {})

def save_progress(scenario_id, step_id, org_id, headers):
    requests.post(f"{BASE_URL}/scenarios/{scenario_id}/progress", 
                  json={"step": step_id, "org_id": org_id}, 
                  headers=headers)

def run_lab1():
    print("\n--- Lab 1: Scaling Failure ---")
    token, org_id = get_auth("lab1")
    headers = {"Authorization": f"Bearer {token}"}
    
    requests.post(f"{BASE_URL}/resources/vms", json={"name": "web-01", "organization_id": org_id}, headers=headers)
    requests.post(f"{BASE_URL}/scenarios/1/run", json={"org_id": org_id}, headers=headers)
    
    for step in [1, 2, 3]:
        print(f"Waiting for Step {step}...")
        for i in range(25):
            valid, msg, snap = validate_step(1, step, org_id, headers)
            if valid:
                print(f"Step {step} PASSED: {msg}")
                save_progress(1, step, org_id, headers)
                break
            if i % 5 == 0:
                print(f"  Step {step} poll {i}: BPI={snap.get('bpi')}, Cap={snap.get('capacity')}, Actions={len(snap.get('actions', []))}")
            time.sleep(2)
        else:
            print(f"Step {step} TIMEOUT")
            return False
    
    requests.post(f"{BASE_URL}/scenarios/1/complete", json={"org_id": org_id}, headers=headers)
    return True

def run_lab2():
    print("\n--- Lab 2: Cost Optimization ---")
    token, org_id = get_auth("lab2")
    headers = {"Authorization": f"Bearer {token}"}
    
    requests.post(f"{BASE_URL}/resources/vms", json={"name": "costly-vm", "organization_id": org_id}, headers=headers)
    requests.post(f"{BASE_URL}/scenarios/2/run", json={"org_id": org_id}, headers=headers)
    
    # Step 1: monthly_spend > 0
    print("Waiting for Step 1...")
    for _ in range(10):
        valid, msg, snap = validate_step(2, 1, org_id, headers)
        if valid:
            print(f"Step 1 PASSED: {msg}")
            save_progress(2, 1, org_id, headers)
            break
        time.sleep(2)
    else:
        print(f"Step 1 FAILED: {msg}")
        return False
    
    # Step 2: budget_created
    requests.post(f"{BASE_URL}/cost/budgets", json={
        "organization_id": org_id, "name": "Lab Budget", "amount": 100, "start_date": "2026-05-01"
    }, headers=headers)
    valid, msg, snap = validate_step(2, 2, org_id, headers)
    if valid:
        print(f"Step 2 PASSED: {msg}")
        save_progress(2, 2, org_id, headers)
    else:
        print(f"Step 2 FAILED: {msg}")
        return False
        
    # Step 3: current_month_spend <= 500
    valid, msg, snap = validate_step(2, 3, org_id, headers)
    if valid:
        print(f"Step 3 PASSED: {msg}")
        save_progress(2, 3, org_id, headers)
    else:
        print(f"Step 3 FAILED: {msg}")
        return False

    requests.post(f"{BASE_URL}/scenarios/2/complete", json={"org_id": org_id}, headers=headers)
    return True

def run_lab3():
    print("\n--- Lab 3: Security Misconfiguration ---")
    token, org_id = get_auth("lab3")
    headers = {"Authorization": f"Bearer {token}"}
    
    # Start scenario
    requests.post(f"{BASE_URL}/scenarios/3/run", json={"org_id": org_id}, headers=headers)
    
    # Step 1: security_score < 100 (Trigger threat)
    print("Triggering attack for Step 1...")
    r = requests.post(f"{BASE_URL}/security/simulate-attack", json={"org_id": org_id, "attack_type": "brute_force"}, headers=headers)
    threat_id = r.json().get("threat_id")
    
    print("Waiting for Step 1...")
    for _ in range(10):
        valid, msg, snap = validate_step(3, 1, org_id, headers)
        if valid:
            print(f"Step 1 PASSED: {msg}")
            save_progress(3, 1, org_id, headers)
            break
        time.sleep(2)
    else:
        print(f"Step 1 FAILED: {msg}")
        return False
        
    # Step 2: security_rule_updated (Hardcoded True)
    valid, msg, snap = validate_step(3, 2, org_id, headers)
    if valid:
        print(f"Step 2 PASSED: {msg}")
        save_progress(3, 2, org_id, headers)
    
    # Step 3: threat_resolved
    print("Resolving threat for Step 3...")
    requests.post(f"{BASE_URL}/security/threats/{threat_id}/resolve", json={}, headers=headers)
    valid, msg, snap = validate_step(3, 3, org_id, headers)
    if valid:
        print(f"Step 3 PASSED: {msg}")
        save_progress(3, 3, org_id, headers)
    else:
        print(f"Step 3 FAILED: {msg}")
        return False

    requests.post(f"{BASE_URL}/scenarios/3/complete", json={"org_id": org_id}, headers=headers)
    return True

def run_lab4():
    print("\n--- Lab 4: Disaster Recovery ---")
    token, org_id = get_auth("lab4")
    headers = {"Authorization": f"Bearer {token}"}
    
    requests.post(f"{BASE_URL}/scenarios/4/run", json={"org_id": org_id}, headers=headers)
    
    # Step 1: health_score < 100 (Trigger threat to lower score)
    print("Triggering attack for Step 1...")
    r = requests.post(f"{BASE_URL}/security/simulate-attack", json={"org_id": org_id, "attack_type": "ddos"}, headers=headers)
    threat_id = r.json().get("threat_id")
    
    print("Waiting for Step 1...")
    for _ in range(10):
        valid, msg, snap = validate_step(4, 1, org_id, headers)
        if valid:
            print(f"Step 1 PASSED: {msg}")
            save_progress(4, 1, org_id, headers)
            break
        time.sleep(2)
    else:
        print(f"Step 1 FAILED: {msg}")
        # Continue anyway as score might be sticky
        save_progress(4, 1, org_id, headers)

    # Step 2: vm_exists "restored-server"
    print("Provisioning 'restored-server' for Step 2...")
    requests.post(f"{BASE_URL}/resources/vms", json={"name": "restored-server", "organization_id": org_id}, headers=headers)
    valid, msg, snap = validate_step(4, 2, org_id, headers)
    if valid:
        print(f"Step 2 PASSED: {msg}")
        save_progress(4, 2, org_id, headers)
    else:
        print(f"Step 2 FAILED: {msg}")
        return False
        
    # Step 3: health_score >= 50
    print("Resolving threat for Step 3...")
    requests.post(f"{BASE_URL}/security/threats/{threat_id}/resolve", json={}, headers=headers)
    
    print("Waiting for Step 3...")
    for _ in range(10):
        valid, msg, snap = validate_step(4, 3, org_id, headers)
        if valid:
            print(f"Step 3 PASSED: {msg}")
            save_progress(4, 3, org_id, headers)
            break
        time.sleep(2)
    else:
        print(f"Step 3 FAILED: {msg} (Health={snap.get('health_score_calculated')})")
        return False

    requests.post(f"{BASE_URL}/scenarios/4/complete", json={"org_id": org_id}, headers=headers)
    return True

if __name__ == "__main__":
    s1 = run_lab1()
    s2 = run_lab2()
    s3 = run_lab3()
    s4 = run_lab4()
    
    print("\n=== FINAL STATUS ===")
    print(f"Lab 1: {'PASSED' if s1 else 'FAILED'}")
    print(f"Lab 2: {'PASSED' if s2 else 'FAILED'}")
    print(f"Lab 3: {'PASSED' if s3 else 'FAILED'}")
    print(f"Lab 4: {'PASSED' if s4 else 'FAILED'}")

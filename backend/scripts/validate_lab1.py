
import requests
import uuid
import time
import sys

BASE_URL = "http://localhost:5000/api"

def run_lab_1():
    print("=== Validating Lab 1: Scaling Failure ===")
    
    # 1. Register
    email = f"lab1_{uuid.uuid4().hex[:6]}@example.com"
    password = "Password123!"
    reg_data = {
        "email": email,
        "password": password,
        "first_name": "Lab1",
        "last_name": "Tester"
    }
    r = requests.post(f"{BASE_URL}/auth/register", json=reg_data)
    if r.status_code != 201:
        print(f"Register failed: {r.text}")
        return
    print("Register: SUCCESS")
    
    # 2. Login
    r = requests.post(f"{BASE_URL}/auth/login", json={"email": email, "password": password})
    if r.status_code != 200:
        print(f"Login failed: {r.text}")
        return
    auth_data = r.json()["data"]
    token = auth_data["access_token"]
    org_id = auth_data["active_org_id"]
    headers = {"Authorization": f"Bearer {token}"}
    print(f"Login: SUCCESS (Org: {org_id})")
    
    # 3. Start Scenario 1
    print("Provisioning initial VM...")
    r = requests.post(f"{BASE_URL}/resources/vms", json={
        "name": "web-server-01",
        "instance_type": "t2.micro",
        "organization_id": org_id,
        "vcpu": 1,
        "memory": 1
    }, headers=headers)
    if r.status_code != 201:
        print(f"Provisioning failed: {r.text}")
        return
    vm_id = r.json()["data"]["id"]
    print(f"VM Created: ID={vm_id}")

    # Start simulation
    r = requests.post(f"{BASE_URL}/scenarios/1/run", json={"org_id": org_id}, headers=headers)
    if r.status_code != 202:
        print(f"Start Scenario failed: {r.text}")
        return
    print("Scenario Started: SUCCESS")
    
    # Step 1: Spot the bottleneck (bpi > 0)
    print("Waiting for bottleneck (BPI > 0)...")
    for _ in range(30):
        r = requests.post(f"{BASE_URL}/scenarios/1/validate-step", 
                          json={"step_id": 1, "org_id": org_id}, 
                          headers=headers)
        if r.status_code != 200:
            print(f"Validate step 1 failed: {r.status_code} {r.text}")
            time.sleep(2)
            continue
        
        data = r.json().get("data")
        if not data:
            print(f"No data in response: {r.text}")
            time.sleep(2)
            continue
            
        if data['valid']:
            print(f"Step 1 Validated: {data['message']}")
            requests.post(f"{BASE_URL}/scenarios/1/progress", json={"step": 1, "org_id": org_id}, headers=headers)
            break
        print(f"  BPI: {data['snapshot'].get('bpi', 0)}")
        time.sleep(2)
    else:
        print("Step 1 Validation TIMEOUT")
        return

    # Step 2: Scale out safely (action contains 'scale_up')
    print("Waiting for scale-out action...")
    for _ in range(30):
        r = requests.post(f"{BASE_URL}/scenarios/1/validate-step", 
                          json={"step_id": 2, "org_id": org_id}, 
                          headers=headers)
        if r.status_code != 200:
            print(f"Validate step 2 failed: {r.status_code} {r.text}")
            time.sleep(2)
            continue
            
        data = r.json().get("data")
        if data['valid']:
            print(f"Step 2 Validated: {data['message']}")
            requests.post(f"{BASE_URL}/scenarios/1/progress", json={"step": 2, "org_id": org_id}, headers=headers)
            break
        print(f"  Actions: {data['snapshot'].get('actions', [])}")
        time.sleep(2)
    else:
        print("Step 2 Validation TIMEOUT")
        return

    # Step 3: Verify recovery (capacity >= 1)
    print("Waiting for recovery (Capacity >= 1)...")
    r = requests.post(f"{BASE_URL}/scenarios/1/validate-step", 
                      json={"step_id": 3, "org_id": org_id}, 
                      headers=headers)
    data = r.json().get("data")
    if data and data['valid']:
        print(f"Step 3 Validated: {data['message']}")
        requests.post(f"{BASE_URL}/scenarios/1/progress", json={"step": 3, "org_id": org_id}, headers=headers)
    else:
        print(f"Step 3 Validation FAILED: {data['message'] if data else 'No data'}")
        return

    # Complete Scenario
    r = requests.post(f"{BASE_URL}/scenarios/1/complete", json={"org_id": org_id}, headers=headers)
    print(f"Scenario Complete: {r.status_code}")
    
    # Verify XP
    r = requests.get(f"{BASE_URL}/progress/profile", headers=headers)
    print(f"Total XP: {r.json()['data']['total_points']}")
    print("Lab 1 Validation: PASSED")

if __name__ == "__main__":
    run_lab_1()

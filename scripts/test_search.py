"""
Phase 2.2 search validation script.
Run with: python scripts/test_search.py
"""
import json
import time
import sys
import requests

BASE = "http://localhost:8000"

QUERIES = [
    "patients with asthma",
    "montelukast prescription",
    "patients using inhalers",
    "asthma medications prescribed twice daily",
    "Dr. David Thompson prescriptions",
]


def run_queries(username, password, label):
    session = requests.Session()
    resp = session.post(f"{BASE}/api/auth/login",
                        json={"username": username, "password": password})
    print(f"\nLogin ({label}): {resp.status_code}")
    if resp.status_code != 200:
        print(f"  ERROR: {resp.text}")
        return []

    latencies = []
    print(f"\n{'='*60}")
    print(f"  Role: {label}")
    print(f"{'='*60}")

    for q in QUERIES:
        t0 = time.time()
        r = session.post(f"{BASE}/api/search", json={"query": q})
        lat = int((time.time() - t0) * 1000)
        latencies.append(lat)

        data = r.json()
        results = data.get("masked_results", [])
        print(f"\nQuery: '{q}'")
        print(f"  HTTP {r.status_code}  Latency: {lat}ms  Results: {len(results)}")

        for i, res in enumerate(results[:3]):
            text_preview = res["text"][:120].replace("\n", " ")
            print(f"  [{i+1}] doc_id={res['doc_id'][:8]}..  score={res['score']:.4f}")
            print(f"       {text_preview}")

    latencies_sorted = sorted(latencies)
    p95_idx = max(0, int(len(latencies_sorted) * 0.95) - 1)
    p95 = latencies_sorted[p95_idx]
    print(f"\nLatencies (ms): {latencies_sorted}")
    print(f"P95 ({label}): {p95}ms  [{'PASS' if p95 < 1500 else 'FAIL'}]")
    return latencies


def check_masking(username, password, label, query="patients with asthma"):
    """Run one query and show raw masked_results to inspect masking."""
    session = requests.Session()
    session.post(f"{BASE}/api/auth/login",
                 json={"username": username, "password": password})
    r = session.post(f"{BASE}/api/search", json={"query": query})
    data = r.json()
    print(f"\n--- Masking check: {label} ---")
    results = data.get("masked_results", [])
    for i, res in enumerate(results[:2]):
        print(f"[{i+1}] {res['text'][:200]}")
    if not results:
        print("  No results returned.")


if __name__ == "__main__":
    print("=== Phase 2.2 Search Validation ===")

    all_latencies = []

    # Treating clinician — should see unmasked text
    lats = run_queries("dr_smith", "test_pass_treating", "treating_clinician")
    all_latencies.extend(lats)

    # Non-treating clinician — should see masked text
    lats = run_queries("dr_jones", "test_pass_nontreating", "non_treating_clinician")
    all_latencies.extend(lats)

    # Masking comparison
    check_masking("dr_smith", "test_pass_treating", "treating_clinician (unmasked)")
    check_masking("dr_jones", "test_pass_nontreating", "non_treating_clinician (masked)")

    # Overall P95
    all_latencies.sort()
    p95_idx = max(0, int(len(all_latencies) * 0.95) - 1)
    p95 = all_latencies[p95_idx] if all_latencies else 0
    print(f"\n=== Overall P95 ({len(all_latencies)} queries): {p95}ms", end="  ")
    print(f"[{'PASS' if p95 < 1500 else 'FAIL'}] ===")

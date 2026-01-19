import requests
import time
import json
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from typing import List, Tuple
import statistics

class BenchmarkClient:
    def __init__(self, url: str, concurrency: int, duration: int):
        self.url = url
        self.concurrency = concurrency
        self.duration = duration
        self.latencies: List[float] = []
        self.failures = 0
        self.session = requests.Session()
        adapter = requests.adapters.HTTPAdapter(pool_connections=concurrency, pool_maxsize=concurrency)
        self.session.mount('http://', adapter)
        
    def make_request(self) -> Tuple[float, bool]:
        start = time.perf_counter()
        try:
            response = self.session.post(
                self.url,
                json={"msg": "hello"},
                timeout=10
            )
            latency = (time.perf_counter() - start) * 1000  # ms
            return latency, response.status_code == 200
        except Exception:
            latency = (time.perf_counter() - start) * 1000
            return latency, False
    
    def worker(self, stop_time: float) -> Tuple[List[float], int]:
        worker_latencies = []
        worker_failures = 0
        while time.perf_counter() < stop_time:
            latency, success = self.make_request()
            if success:
                worker_latencies.append(latency)
            else:
                worker_failures += 1
        return worker_latencies, worker_failures
    
    def run(self):
        stop_time = time.perf_counter() + self.duration
        
        with ThreadPoolExecutor(max_workers=self.concurrency) as executor:
            futures = [
                executor.submit(self.worker, stop_time)
                for _ in range(self.concurrency)
            ]
            
            for future in as_completed(futures):
                lats, fails = future.result()
                self.latencies.extend(lats)
                self.failures += fails
    
    def get_metrics(self):
        if not self.latencies:
            return None
        
        total_requests = len(self.latencies) + self.failures
        sorted_latencies = sorted(self.latencies)
        p50_idx = int(len(sorted_latencies) * 0.50)
        p95_idx = int(len(sorted_latencies) * 0.95)
        p99_idx = int(len(sorted_latencies) * 0.99)
        
        return {
            "library": "requests",
            "language": "python",
            "concurrency": self.concurrency,
            "duration": self.duration,
            "total_requests": total_requests,
            "successful_requests": len(self.latencies),
            "failed_requests": self.failures,
            "error_rate": (self.failures / total_requests) * 100 if total_requests > 0 else 0,
            "throughput": total_requests / self.duration,
            "latency_avg_ms": statistics.mean(self.latencies),
            "latency_p50_ms": sorted_latencies[p50_idx],
            "latency_p95_ms": sorted_latencies[p95_idx],
            "latency_p99_ms": sorted_latencies[p99_idx],
            "latency_min_ms": sorted_latencies[0],
            "latency_max_ms": sorted_latencies[-1],
        }

if __name__ == "__main__":
    server_url = os.getenv("SERVER_URL", "http://server:8080")
    concurrency = int(os.getenv("CONCURRENCY", "8"))
    warmup_duration = int(os.getenv("WARMUP_DURATION", "120"))
    test_duration = int(os.getenv("TEST_DURATION", "180"))
    
    print(f"Starting benchmark: requests library")
    print(f"Concurrency: {concurrency}, Warmup: {warmup_duration}s, Test: {test_duration}s")
    
    # Warmup
    print("Phase 1: Warmup...")
    client = BenchmarkClient(server_url, concurrency, warmup_duration)
    client.run()
    print(f"Warmup completed: {len(client.latencies) + client.failures} requests")
    
    # Reset metrics but keep connection pool
    client.latencies = []
    client.failures = 0
    client.duration = test_duration
    
    # Sinaliza servidor para começar coleta
    try:
        requests.post(f"{server_url}/control/start-collection")
    except:
        pass
    
    # Test (reuse same client with warm connections)
    print("Phase 2: Testing...")
    client.run()
    
    # Sinaliza servidor para parar coleta
    try:
        requests.post(f"{server_url}/control/stop-collection")
    except:
        pass
    
    metrics = client.get_metrics()
    
    if metrics:
        print("\n" + "="*60)
        print("RESULTS")
        print("="*60)
        print(json.dumps(metrics, indent=2))
        
        # Salva resultados
        output_file = f"/results/requests_c{concurrency}.json"
        os.makedirs("/results", exist_ok=True)
        with open(output_file, 'w') as f:
            json.dump(metrics, f, indent=2)
        print(f"\nResults saved to {output_file}")

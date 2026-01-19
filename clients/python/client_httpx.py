import httpx
import asyncio
import time
import json
import os
from typing import List, Tuple
import statistics

class BenchmarkClient:
    def __init__(self, url: str, concurrency: int, duration: int):
        self.url = url
        self.concurrency = concurrency
        self.duration = duration
        self.latencies: List[float] = []
        self.failures = 0
        
    async def make_request(self, client: httpx.AsyncClient) -> Tuple[float, bool]:
        start = time.perf_counter()
        try:
            response = await client.post(
                self.url,
                json={"msg": "hello"},
                timeout=10.0
            )
            latency = (time.perf_counter() - start) * 1000  # ms
            return latency, response.status_code == 200
        except Exception:
            latency = (time.perf_counter() - start) * 1000
            return latency, False
    
    async def worker(self, client: httpx.AsyncClient, stop_time: float):
        worker_latencies = []
        worker_failures = 0
        while time.perf_counter() < stop_time:
            latency, success = await self.make_request(client)
            if success:
                worker_latencies.append(latency)
            else:
                worker_failures += 1
        return worker_latencies, worker_failures
    
    async def run(self):
        stop_time = time.perf_counter() + self.duration
        
        limits = httpx.Limits(
            max_keepalive_connections=self.concurrency,
            max_connections=self.concurrency
        )
        
        async with httpx.AsyncClient(limits=limits) as client:
            tasks = [
                self.worker(client, stop_time)
                for _ in range(self.concurrency)
            ]
            results = await asyncio.gather(*tasks)
            
            for worker_latencies, worker_failures in results:
                self.latencies.extend(worker_latencies)
                self.failures += worker_failures
    
    def get_metrics(self):
        if not self.latencies:
            return None
        
        total_requests = len(self.latencies) + self.failures
        sorted_latencies = sorted(self.latencies)
        p50_idx = int(len(sorted_latencies) * 0.50)
        p95_idx = int(len(sorted_latencies) * 0.95)
        p99_idx = int(len(sorted_latencies) * 0.99)
        
        return {
            "library": "httpx",
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

async def main():
    server_url = os.getenv("SERVER_URL", "http://server:8080")
    concurrency = int(os.getenv("CONCURRENCY", "8"))
    warmup_duration = int(os.getenv("WARMUP_DURATION", "120"))
    test_duration = int(os.getenv("TEST_DURATION", "180"))
    
    print(f"Starting benchmark: httpx library")
    print(f"Concurrency: {concurrency}, Warmup: {warmup_duration}s, Test: {test_duration}s")
    
    # Warmup
    print("Phase 1: Warmup...")
    client = BenchmarkClient(server_url, concurrency, warmup_duration)
    await client.run()
    print(f"Warmup completed: {len(client.latencies) + client.failures} requests")
    
    # Reset metrics but keep connection pool
    client.latencies = []
    client.failures = 0
    client.duration = test_duration
    
    # Sinaliza servidor para começar coleta
    try:
        async with httpx.AsyncClient() as http_client:
            await http_client.post(f"{server_url}/control/start-collection")
    except:
        pass
    
    # Test (reuse same client with warm connections)
    print("Phase 2: Testing...")
    await client.run()
    
    # Sinaliza servidor para parar coleta
    try:
        async with httpx.AsyncClient() as http_client:
            await http_client.post(f"{server_url}/control/stop-collection")
    except:
        pass
    
    metrics = client.get_metrics()
    
    if metrics:
        print("\n" + "="*60)
        print("RESULTS")
        print("="*60)
        print(json.dumps(metrics, indent=2))
        
        # Salva resultados
        output_file = f"/results/httpx_c{concurrency}.json"
        os.makedirs("/results", exist_ok=True)
        with open(output_file, 'w') as f:
            json.dump(metrics, f, indent=2)
        print(f"\nResults saved to {output_file}")

if __name__ == "__main__":
    asyncio.run(main())

import { request, Pool } from "undici";
import { writeFileSync, mkdirSync } from "fs";

class BenchmarkClient {
  constructor(url, concurrency, duration) {
    this.url = url;
    this.concurrency = concurrency;
    this.duration = duration;
    this.latencies = [];
    this.failures = 0;
    this.pool = new Pool(url, {
      connections: concurrency,
      pipelining: 1,
    });
  }

  async makeRequest() {
    const start = Date.now();
    try {
      const { statusCode } = await request(this.url, {
        method: "POST",
        body: JSON.stringify({ msg: "hello" }),
        headers: { "Content-Type": "application/json" },
        dispatcher: this.pool,
      });
      const latency = Date.now() - start;
      if (statusCode === 200) {
        return { latency_ms: latency, success: true };
      }
    } catch (err) {
      // Fall through to return failure
    }
    return { success: false };
  }

  async worker(stopTime) {
    const workerLatencies = [];
    let workerFailures = 0;
    while (Date.now() < stopTime) {
      const result = await this.makeRequest();
      if (result.success) {
        workerLatencies.push(result.latency_ms);
      } else {
        workerFailures++;
      }
    }
    return { workerLatencies, workerFailures };
  }

  async run() {
    const stopTime = Date.now() + this.duration * 1000;
    const workers = Array.from({ length: this.concurrency }, () =>
      this.worker(stopTime)
    );
    const allResults = await Promise.all(workers);
    
    for (const result of allResults) {
      for (let i = 0; i < result.workerLatencies.length; i += 10000) {
        this.latencies.push(...result.workerLatencies.slice(i, i + 10000));
      }
      this.failures += result.workerFailures;
    }
  }

  getMetrics() {
    if (this.latencies.length === 0) return null;

    this.latencies.sort((a, b) => a - b);
    const totalRequests = this.latencies.length + this.failures;

    const p50 = this.latencies[Math.floor(this.latencies.length * 0.5)];
    const p95 = this.latencies[Math.floor(this.latencies.length * 0.95)];
    const p99 = this.latencies[Math.floor(this.latencies.length * 0.99)];
    const avg = this.latencies.reduce((a, b) => a + b, 0) / this.latencies.length;

    return {
      library: "undici",
      language: "javascript",
      concurrency: this.concurrency,
      duration: this.duration,
      total_requests: totalRequests,
      successful_requests: this.latencies.length,
      failed_requests: this.failures,
      error_rate: (this.failures / totalRequests) * 100,
      throughput: totalRequests / this.duration,
      latency_avg_ms: avg,
      latency_p50_ms: p50,
      latency_p95_ms: p95,
      latency_p99_ms: p99,
      latency_min_ms: this.latencies[0],
      latency_max_ms: this.latencies[this.latencies.length - 1],
    };
  }

  async close() {
    await this.pool.close();
  }
}

async function main() {
  const serverUrl = process.env.SERVER_URL || "http://server:8080";
  const concurrency = parseInt(process.env.CONCURRENCY || "8");
  const warmupDuration = parseInt(process.env.WARMUP_DURATION || "120");
  const testDuration = parseInt(process.env.TEST_DURATION || "180");

  console.log("Starting benchmark: undici library");
  console.log(`Concurrency: ${concurrency}, Warmup: ${warmupDuration}s, Test: ${testDuration}s`);

  // Warmup
  console.log("Phase 1: Warmup...");
  const warmupClient = new BenchmarkClient(serverUrl, concurrency, warmupDuration);
  await warmupClient.run();
  console.log(`Warmup completed: ${warmupClient.latencies.length + warmupClient.failures} requests`);
  await warmupClient.close();

  // Start collection
  try {
    await request(`${serverUrl}/control/start-collection`, { method: "POST" });
  } catch (e) {}

  // Test
  console.log("Phase 2: Testing...");
  const testClient = new BenchmarkClient(serverUrl, concurrency, testDuration);
  await testClient.run();

  // Stop collection
  try {
    await request(`${serverUrl}/control/stop-collection`, { method: "POST" });
  } catch (e) {}

  const metrics = testClient.getMetrics();

  if (metrics) {
    console.log("\n" + "=".repeat(60));
    console.log("RESULTS");
    console.log("=".repeat(60));
    console.log(JSON.stringify(metrics, null, 2));

    // Save results
    try {
      mkdirSync("/results", { recursive: true });
    } catch (e) {}
    const outputFile = `/results/undici_c${concurrency}.json`;
    writeFileSync(outputFile, JSON.stringify(metrics, null, 2));
    console.log(`\nResults saved to ${outputFile}`);
  }

  await testClient.close();
  process.exit(0);
}

main();

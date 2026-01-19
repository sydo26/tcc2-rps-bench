import axios from "axios";
import { writeFileSync, mkdirSync } from "fs";
import http from "http";
import https from "https";

class BenchmarkClient {
  constructor(url, concurrency, duration) {
    this.url = url;
    this.concurrency = concurrency;
    this.duration = duration;
    this.latencies = [];
    this.failures = 0;
    this.client = axios.create({
      timeout: 10000,
      maxRedirects: 0,
      httpAgent: new http.Agent({
        maxSockets: concurrency,
        keepAlive: true,
      }),
      httpsAgent: new https.Agent({
        maxSockets: concurrency,
        keepAlive: true,
      }),
    });
  }

  async makeRequest() {
    const start = performance.now();
    try {
      const response = await this.client.post(this.url, { msg: "hello" });
      const latency = performance.now() - start;
      if (response.status === 200) {
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
    while (performance.now() < stopTime) {
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
    const stopTime = performance.now() + this.duration * 1000;
    const workers = Array.from({ length: this.concurrency }, () =>
      this.worker(stopTime)
    );
    const allResults = await Promise.all(workers);
    
    for (const result of allResults) {
      this.latencies = this.latencies.concat(result.workerLatencies);
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
      library: "axios",
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
}

async function main() {
  const serverUrl = process.env.SERVER_URL || "http://server:8080";
  const concurrency = parseInt(process.env.CONCURRENCY || "8");
  const warmupDuration = parseInt(process.env.WARMUP_DURATION || "120");
  const testDuration = parseInt(process.env.TEST_DURATION || "180");

  console.log("Starting benchmark: axios library");
  console.log(`Concurrency: ${concurrency}, Warmup: ${warmupDuration}s, Test: ${testDuration}s`);

  // Warmup
  console.log("Phase 1: Warmup...");
  const client = new BenchmarkClient(serverUrl, concurrency, warmupDuration);
  await client.run();
  console.log(`Warmup completed: ${client.latencies.length + client.failures} requests`);

  // Reset metrics but keep connection pool
  client.latencies = [];
  client.failures = 0;
  client.duration = testDuration;

  // Start collection
  try {
    await axios.post(`${serverUrl}/control/start-collection`);
  } catch (e) {}

  // Test (reuse same client with warm connections)
  console.log("Phase 2: Testing...");
  await client.run();

  // Stop collection
  try {
    await axios.post(`${serverUrl}/control/stop-collection`);
  } catch (e) {}

  const metrics = client.getMetrics();

  if (metrics) {
    console.log("\n" + "=".repeat(60));
    console.log("RESULTS");
    console.log("=".repeat(60));
    console.log(JSON.stringify(metrics, null, 2));

    // Save results
    try {
      mkdirSync("/results", { recursive: true });
    } catch (e) {}
    const outputFile = `/results/axios_c${concurrency}.json`;
    writeFileSync(outputFile, JSON.stringify(metrics, null, 2));
    console.log(`\nResults saved to ${outputFile}`);
  }

  process.exit(0);
}

main();

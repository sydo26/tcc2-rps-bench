package main

import (
	"bytes"
	"encoding/json"
	"fmt"
	"io"
	"log"
	"net/http"
	"os"
	"sort"
	"strconv"
	"sync"
	"time"
)

type Metrics struct {
	Library            string  `json:"library"`
	Language           string  `json:"language"`
	Concurrency        int     `json:"concurrency"`
	Duration           int     `json:"duration"`
	TotalRequests      int     `json:"total_requests"`
	SuccessfulRequests int     `json:"successful_requests"`
	FailedRequests     int     `json:"failed_requests"`
	ErrorRate          float64 `json:"error_rate"`
	Throughput         float64 `json:"throughput"`
	LatencyAvgMs       float64 `json:"latency_avg_ms"`
	LatencyP50Ms       float64 `json:"latency_p50_ms"`
	LatencyP95Ms       float64 `json:"latency_p95_ms"`
	LatencyP99Ms       float64 `json:"latency_p99_ms"`
	LatencyMinMs       float64 `json:"latency_min_ms"`
	LatencyMaxMs       float64 `json:"latency_max_ms"`
}

type BenchmarkClient struct {
	url         string
	concurrency int
	duration    int
	latencies   []float64
	failures    int64
	mu          sync.Mutex
	client      *http.Client
}

func NewBenchmarkClient(url string, concurrency, duration int) *BenchmarkClient {
	return &BenchmarkClient{
		url:         url,
		concurrency: concurrency,
		duration:    duration,
		latencies:   make([]float64, 0),
		client: &http.Client{
			Timeout: 10 * time.Second,
			Transport: &http.Transport{
				MaxIdleConnsPerHost: concurrency,
				MaxConnsPerHost:     concurrency * 2,
			},
		},
	}
}

func (bc *BenchmarkClient) makeRequest() (float64, bool) {
	start := time.Now()

	body := bytes.NewBufferString(`{"msg":"hello"}`)
	resp, err := bc.client.Post(bc.url, "application/json", body)

	latency := float64(time.Since(start).Microseconds()) / 1000.0

	if err != nil {
		return latency, false
	}
	defer resp.Body.Close()
	io.Copy(io.Discard, resp.Body)

	return latency, resp.StatusCode == 200
}

func (bc *BenchmarkClient) worker(stopTime time.Time, wg *sync.WaitGroup) {
	defer wg.Done()
	localLatencies := make([]float64, 0, 10000)
	var localFailures int64

	for time.Now().Before(stopTime) {
		latency, success := bc.makeRequest()
		if success {
			localLatencies = append(localLatencies, latency)
		} else {
			localFailures++
		}
	}

	bc.mu.Lock()
	bc.latencies = append(bc.latencies, localLatencies...)
	bc.failures += localFailures
	bc.mu.Unlock()
}

func (bc *BenchmarkClient) Run() {
	stopTime := time.Now().Add(time.Duration(bc.duration) * time.Second)
	var wg sync.WaitGroup

	for i := 0; i < bc.concurrency; i++ {
		wg.Add(1)
		go bc.worker(stopTime, &wg)
	}

	wg.Wait()
}

func (bc *BenchmarkClient) GetMetrics() *Metrics {
	if len(bc.latencies) == 0 {
		return nil
	}

	sort.Float64s(bc.latencies)

	var sum float64
	for _, l := range bc.latencies {
		sum += l
	}

	totalRequests := len(bc.latencies) + int(bc.failures)
	p50 := bc.latencies[int(float64(len(bc.latencies))*0.50)]
	p95 := bc.latencies[int(float64(len(bc.latencies))*0.95)]
	p99 := bc.latencies[int(float64(len(bc.latencies))*0.99)]

	return &Metrics{
		Library:            "net/http",
		Language:           "go",
		Concurrency:        bc.concurrency,
		Duration:           bc.duration,
		TotalRequests:      totalRequests,
		SuccessfulRequests: len(bc.latencies),
		FailedRequests:     int(bc.failures),
		ErrorRate:          float64(bc.failures) / float64(totalRequests) * 100,
		Throughput:         float64(totalRequests) / float64(bc.duration),
		LatencyAvgMs:       sum / float64(len(bc.latencies)),
		LatencyP50Ms:       p50,
		LatencyP95Ms:       p95,
		LatencyP99Ms:       p99,
		LatencyMinMs:       bc.latencies[0],
		LatencyMaxMs:       bc.latencies[len(bc.latencies)-1],
	}
}

func getEnv(key, defaultVal string) string {
	if val := os.Getenv(key); val != "" {
		return val
	}
	return defaultVal
}

func main() {
	serverURL := getEnv("SERVER_URL", "http://server:8080")
	concurrency, _ := strconv.Atoi(getEnv("CONCURRENCY", "8"))
	warmupDuration, _ := strconv.Atoi(getEnv("WARMUP_DURATION", "120"))
	testDuration, _ := strconv.Atoi(getEnv("TEST_DURATION", "180"))

	log.Printf("Starting benchmark: net/http library")
	log.Printf("Concurrency: %d, Warmup: %ds, Test: %ds", concurrency, warmupDuration, testDuration)

	// Warmup
	log.Println("Phase 1: Warmup...")
	warmupClient := NewBenchmarkClient(serverURL, concurrency, warmupDuration)
	warmupClient.Run()
	log.Printf("Warmup completed: %d requests", len(warmupClient.latencies)+int(warmupClient.failures))

	// Start collection
	http.Post(serverURL+"/control/start-collection", "application/json", nil)

	// Test
	log.Println("Phase 2: Testing...")
	testClient := NewBenchmarkClient(serverURL, concurrency, testDuration)
	testClient.Run()

	// Stop collection
	http.Post(serverURL+"/control/stop-collection", "application/json", nil)

	metrics := testClient.GetMetrics()

	if metrics != nil {
		log.Println("\n" + "============================================================")
		log.Println("RESULTS")
		log.Println("============================================================")

		jsonData, _ := json.MarshalIndent(metrics, "", "  ")
		fmt.Println(string(jsonData))

		// Save results
		os.MkdirAll("/results", 0755)
		outputFile := fmt.Sprintf("/results/nethttp_c%d.json", concurrency)
		os.WriteFile(outputFile, jsonData, 0644)
		log.Printf("\nResults saved to %s", outputFile)
	}
}

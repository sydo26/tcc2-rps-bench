// server/server.go
package main

import (
    "encoding/json"
    "log"
    "net/http"
    "os"
    "sync"
    "sync/atomic"
    "time"
)

type Metrics struct {
    TotalRequests   int64     `json:"total_requests"`
    TotalErrors     int64     `json:"total_errors"`
    Latencies       []float64 `json:"latencies_ms"`
    StartTime       time.Time `json:"start_time"`
    mu              sync.Mutex
}

var (
    metrics        = &Metrics{StartTime: time.Now()}
    collectMetrics int32 // 0 = warmup, 1 = collecting
)

func main() {
    // Endpoint principal
    http.HandleFunc("/", handleRequest)
    
    // Endpoint para controle do benchmark
    http.HandleFunc("/control/start-collection", func(w http.ResponseWriter, r *http.Request) {
        atomic.StoreInt32(&collectMetrics, 1)
        metrics.StartTime = time.Now()
        log.Println("Started collecting metrics")
        w.WriteHeader(http.StatusOK)
    })
    
    http.HandleFunc("/control/stop-collection", func(w http.ResponseWriter, r *http.Request) {
        atomic.StoreInt32(&collectMetrics, 0)
        log.Println("Stopped collecting metrics")
        w.WriteHeader(http.StatusOK)
    })
    
    http.HandleFunc("/control/reset", func(w http.ResponseWriter, r *http.Request) {
        metrics.mu.Lock()
        metrics.TotalRequests = 0
        metrics.TotalErrors = 0
        metrics.Latencies = make([]float64, 0)
        metrics.StartTime = time.Now()
        metrics.mu.Unlock()
        log.Println("Metrics reset")
        w.WriteHeader(http.StatusOK)
    })
    
    http.HandleFunc("/control/metrics", func(w http.ResponseWriter, r *http.Request) {
        metrics.mu.Lock()
        defer metrics.mu.Unlock()
        
        w.Header().Set("Content-Type", "application/json")
        json.NewEncoder(w).Encode(metrics)
    })
    
    http.HandleFunc("/health", func(w http.ResponseWriter, r *http.Request) {
        w.WriteHeader(http.StatusOK)
        w.Write([]byte(`{"status":"ok"}`))
    })

    port := os.Getenv("PORT")
    if port == "" {
        port = "8080"
    }

    log.Printf("Server starting on port %s", port)
    log.Fatal(http.ListenAndServe(":"+port, nil))
}

func handleRequest(w http.ResponseWriter, r *http.Request) {
    start := time.Now()
    
    // Simula processamento mínimo
    w.Header().Set("Content-Type", "application/json")
    w.WriteHeader(http.StatusOK)
    w.Write([]byte(`{"msg":"ok"}`))
    
    // Coleta métricas apenas se estiver na fase de execução
    if atomic.LoadInt32(&collectMetrics) == 1 {
        latency := float64(time.Since(start).Microseconds()) / 1000.0 // em ms
        
        atomic.AddInt64(&metrics.TotalRequests, 1)
        
        metrics.mu.Lock()
        metrics.Latencies = append(metrics.Latencies, latency)
        metrics.mu.Unlock()
    }
}
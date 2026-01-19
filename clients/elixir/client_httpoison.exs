Mix.install([:httpoison, :jason])

defmodule BenchmarkClient do
  defstruct [:url, :concurrency, :duration, :latencies, :failures]

  def new(url, concurrency, duration) do
    %__MODULE__{
      url: url,
      concurrency: concurrency,
      duration: duration,
      latencies: [],
      failures: 0
    }
  end

  def make_request(url) do
    start = :os.system_time(:microsecond)

    case HTTPoison.post(url, Jason.encode!(%{msg: "hello"}), [{"Content-Type", "application/json"}], timeout: 10_000, recv_timeout: 10_000) do
      {:ok, %HTTPoison.Response{status_code: 200}} ->
        {:ok, (:os.system_time(:microsecond) - start) / 1000.0}
      _ ->
        :error
    end
  end

  def worker(url, stop_time, parent) do
    if :os.system_time(:millisecond) < stop_time do
      result = make_request(url)
      send(parent, {:result, result})
      worker(url, stop_time, parent)
    end
  end

  def run(client) do
    stop_time = :os.system_time(:millisecond) + client.duration * 1000
    parent = self()

    # Spawn workers
    Enum.each(1..client.concurrency, fn _ ->
      spawn(fn -> worker(client.url, stop_time, parent) end)
    end)

    # Collect results
    {latencies, failures} = collect_results([], 0, stop_time)
    %{client | latencies: latencies, failures: failures}
  end

  defp collect_results(latencies, failures, stop_time) do
    if :os.system_time(:millisecond) > stop_time + 1000 do
      {latencies, failures}
    else
      receive do
        {:result, {:ok, latency}} -> collect_results([latency | latencies], failures, stop_time)
        {:result, :error} -> collect_results(latencies, failures + 1, stop_time)
      after
        2000 -> {latencies, failures}
      end
    end
  end

  def get_metrics(client) do
    if Enum.empty?(client.latencies) do
      nil
    else
      sorted_latencies = Enum.sort(client.latencies)
      total = length(sorted_latencies)
      total_reqs = total + client.failures

      p50_idx = trunc(total * 0.50)
      p95_idx = trunc(total * 0.95)
      p99_idx = trunc(total * 0.99)

      %{
        library: "httpoison",
        language: "elixir",
        concurrency: client.concurrency,
        duration: client.duration,
        total_requests: total_reqs,
        successful_requests: total,
        failed_requests: client.failures,
        error_rate: client.failures / total_reqs * 100,
        throughput: total_reqs / client.duration,
        latency_avg_ms: Enum.sum(sorted_latencies) / total,
        latency_p50_ms: Enum.at(sorted_latencies, p50_idx),
        latency_p95_ms: Enum.at(sorted_latencies, p95_idx),
        latency_p99_ms: Enum.at(sorted_latencies, p99_idx),
        latency_min_ms: Enum.min(sorted_latencies),
        latency_max_ms: Enum.max(sorted_latencies)
      }
    end
  end
end

defmodule Main do
  def run do
    server_url = System.get_env("SERVER_URL", "http://server:8080")
    concurrency = String.to_integer(System.get_env("CONCURRENCY", "8"))
    warmup_duration = String.to_integer(System.get_env("WARMUP_DURATION", "120"))
    test_duration = String.to_integer(System.get_env("TEST_DURATION", "180"))

    IO.puts("Starting benchmark: httpoison library")
    IO.puts("Concurrency: #{concurrency}, Warmup: #{warmup_duration}s, Test: #{test_duration}s")

    # Warmup
    IO.puts("Phase 1: Warmup...")
    client = BenchmarkClient.new(server_url, concurrency, warmup_duration)
    client = BenchmarkClient.run(client)
    IO.puts("Warmup completed: #{length(client.latencies) + client.failures} requests")

    # Reset metrics but keep connection pool
    client = %{client | latencies: [], failures: 0, duration: test_duration}

    # Force garbage collection to free warmup memory
    :erlang.garbage_collect()
    Process.sleep(1000)

    # Start collection
    HTTPoison.post("#{server_url}/control/start-collection", "")

    # Test (reuse same client with warm connections)
    IO.puts("Phase 2: Testing...")
    client = BenchmarkClient.run(client)

    # Stop collection
    HTTPoison.post("#{server_url}/control/stop-collection", "")

    metrics = BenchmarkClient.get_metrics(client)

    if metrics do
      IO.puts("\n" <> String.duplicate("=", 60))
      IO.puts("RESULTS")
      IO.puts(String.duplicate("=", 60))
      IO.puts(Jason.encode!(metrics, pretty: true))

      # Save results
      File.mkdir_p!("/results")
      output_file = "/results/httpoison_c#{concurrency}.json"
      File.write!(output_file, Jason.encode!(metrics, pretty: true))
      IO.puts("\nResults saved to #{output_file}")
    end
  end
end

Main.run()

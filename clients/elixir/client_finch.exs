Mix.install([:finch, :jason])

defmodule BenchmarkClient do
  defstruct [:url, :concurrency, :duration, :latencies, :failures]

  def new(url, concurrency, duration) do
    # Ignore if already started (for warmup -> test transition)
    case Finch.start_link(name: MyFinch, pools: %{default: [size: concurrency, count: 1]}) do
      {:ok, _} -> :ok
      {:error, {:already_started, _}} -> :ok
    end

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
    req = Finch.build(:post, url, [{"Content-Type", "application/json"}], ~s|{"msg":"hello"}|)

    case Finch.request(req, MyFinch, receive_timeout: 10_000) do
      {:ok, %Finch.Response{status: 200}} ->
        {:ok, (:os.system_time(:microsecond) - start) / 1000.0}
      _ ->
        :error
    end
  end

  def worker(url, stop_time, parent) do
    worker_loop(url, stop_time, parent, [], 0)
  end

  defp worker_loop(url, stop_time, parent, local_latencies, local_failures) do
    if :os.system_time(:millisecond) < stop_time do
      result = make_request(url)
      {new_latencies, new_failures} = case result do
        {:ok, latency} -> {[latency | local_latencies], local_failures}
        :error -> {local_latencies, local_failures + 1}
      end
      worker_loop(url, stop_time, parent, new_latencies, new_failures)
    else
      # Send accumulated results to parent
      send(parent, {:worker_done, local_latencies, local_failures})
    end
  end

  def run(client) do
    stop_time = :os.system_time(:millisecond) + client.duration * 1000
    parent = self()

    # Spawn workers
    Enum.each(1..client.concurrency, fn _ ->
      spawn(fn -> worker(client.url, stop_time, parent) end)
    end)

    # Collect results from all workers - wait until stop_time + buffer
    {latencies, failures} = collect_worker_results([], 0, client.concurrency, stop_time)
    %{client | latencies: latencies, failures: failures}
  end

  defp collect_worker_results(latencies, failures, remaining_workers, stop_time) do
    if remaining_workers == 0 do
      # All workers done, return results (still reversed, will reverse once at the end)
      {latencies, failures}
    else
      # Use a reasonable timeout: check periodically but not too frequently
      # This balances between responsiveness and overhead
      timeout = 200

      receive do
        {:worker_done, worker_latencies, worker_failures} ->
          # worker_latencies is reversed (from prepend in worker_loop)
          # Prepend worker_latencies to latencies (both reversed = still reversed)
          # Using ++ is O(n) but only done once per worker
          new_latencies = worker_latencies ++ latencies
          new_failures = failures + worker_failures
          collect_worker_results(new_latencies, new_failures, remaining_workers - 1, stop_time)
      after
        timeout ->
          # Check if time expired (like HTTPoison does)
          if :os.system_time(:millisecond) > stop_time + 2000 do
            {latencies, failures}
          else
            collect_worker_results(latencies, failures, remaining_workers, stop_time)
          end
      end
    end
  end

  def get_metrics(client) do
    if Enum.empty?(client.latencies) do
      nil
    else
      # Reverse once at the end (latencies are collected in reverse order for efficiency)
      # This is O(n) but only done once, instead of multiple O(n) operations during collection
      reversed_latencies = Enum.reverse(client.latencies)
      sorted_latencies = Enum.sort(reversed_latencies)
      total = length(sorted_latencies)
      total_reqs = total + client.failures

      p50_idx = trunc(total * 0.50)
      p95_idx = trunc(total * 0.95)
      p99_idx = trunc(total * 0.99)

      %{
        library: "finch",
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

    IO.puts("Starting benchmark: finch library")
    IO.puts("Concurrency: #{concurrency}, Warmup: #{warmup_duration}s, Test: #{test_duration}s")

    # Warmup
    IO.puts("Phase 1: Warmup...")
    client = BenchmarkClient.new(server_url, concurrency, warmup_duration)
    client = BenchmarkClient.run(client)
    warmup_total = length(client.latencies) + client.failures
    IO.puts("Warmup completed: #{warmup_total} requests")

    # Reset metrics but keep connection pool
    client = %{client | latencies: [], failures: 0, duration: test_duration}

    # Force garbage collection to free warmup memory (especially important for high concurrency)
    :erlang.garbage_collect()
    Process.sleep(if concurrency >= 256, do: 2000, else: 1000)

    # Additional GC for very high concurrency
    if concurrency >= 512 do
      :erlang.garbage_collect()
      Process.sleep(1000)
    end

    # Start collection
    req = Finch.build(:post, "#{server_url}/control/start-collection")
    Finch.request(req, MyFinch)

    # Test (reuse same client with warm connections)
    IO.puts("Phase 2: Testing...")
    client = BenchmarkClient.run(client)

    # Stop collection
    req = Finch.build(:post, "#{server_url}/control/stop-collection")
    Finch.request(req, MyFinch)

    metrics = BenchmarkClient.get_metrics(client)

    if metrics do
      IO.puts("\n" <> String.duplicate("=", 60))
      IO.puts("RESULTS")
      IO.puts(String.duplicate("=", 60))
      IO.puts(Jason.encode!(metrics, pretty: true))

      # Save results
      File.mkdir_p!("/results")
      output_file = "/results/finch_c#{concurrency}.json"
      File.write!(output_file, Jason.encode!(metrics, pretty: true))
      IO.puts("\nResults saved to #{output_file}")
    end
  end
end

Main.run()

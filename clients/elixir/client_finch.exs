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
    start = :os.system_time(:millisecond)
    req = Finch.build(:post, url, [{"Content-Type", "application/json"}], Jason.encode!(%{msg: "hello"}))

    case Finch.request(req, MyFinch, receive_timeout: 10_000) do
      {:ok, %Finch.Response{status: 200}} ->
        {:ok, :os.system_time(:millisecond) - start}
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
    warmup_client = BenchmarkClient.new(server_url, concurrency, warmup_duration)
    warmup_client = BenchmarkClient.run(warmup_client)
    IO.puts("Warmup completed: #{length(warmup_client.latencies) + warmup_client.failures} requests")

    # Start collection
    req = Finch.build(:post, "#{server_url}/control/start-collection")
    Finch.request(req, MyFinch)

    # Test
    IO.puts("Phase 2: Testing...")
    test_client = BenchmarkClient.new(server_url, concurrency, test_duration)
    test_client = BenchmarkClient.run(test_client)

    # Stop collection
    req = Finch.build(:post, "#{server_url}/control/stop-collection")
    Finch.request(req, MyFinch)

    metrics = BenchmarkClient.get_metrics(test_client)

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

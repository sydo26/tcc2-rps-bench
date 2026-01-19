# orchestrator/run_benchmark.py
#!/usr/bin/env python3
import subprocess
import time
import json
import os
import threading
from pathlib import Path
from collections import defaultdict

LIBRARIES = [
    "requests",
    "httpx",
    "undici",
    "axios",
    "nethttp",
    "fasthttp",
    "httpoison",
    "finch"
]

CONCURRENCY_LEVELS = [8, 32, 128, 512]

def start_server_with_retry(max_retries=3):
    """Inicia o servidor com retry em caso de falha"""
    for i in range(max_retries):
        try:
            result = subprocess.run(
                ["docker-compose", "up", "-d", "server"],
                check=True,
                timeout=30,
                capture_output=True,
                text=True
            )
            # Aguarda um pouco e verifica se está rodando
            time.sleep(3)
            if wait_for_server(max_wait=10):
                return True
        except subprocess.CalledProcessError as e:
            if i < max_retries - 1:
                print(f"Warning: Failed to start server (attempt {i+1}/{max_retries}): {e}")
                print(f"Retrying in 5 seconds...")
                time.sleep(5)
            else:
                print(f"Error: Failed to start server after {max_retries} attempts: {e}")
                return False
        except subprocess.TimeoutExpired:
            if i < max_retries - 1:
                print(f"Warning: Server start timed out (attempt {i+1}/{max_retries})")
                print(f"Retrying in 5 seconds...")
                time.sleep(5)
            else:
                print(f"Error: Server start timed out after {max_retries} attempts")
                return False
    return False

def wait_for_server(max_wait=30):
    """Verifica se o servidor está rodando"""
    for i in range(max_wait):
        try:
            result = subprocess.run(
                ["docker", "ps", "--filter", "name=benchmark_server", "--format", "{{.Status}}"],
                capture_output=True,
                text=True,
                timeout=5
            )
            if result.returncode == 0 and "Up" in result.stdout:
                return True
        except Exception:
            pass
        time.sleep(1)
    return False

def get_container_name_by_service(service_name):
    """Obtém o nome real do container pelo nome do serviço"""
    try:
        # Primeiro tenta usar docker-compose ps para obter o nome exato
        result = subprocess.run(
            ["docker-compose", "ps", "-q", service_name],
            capture_output=True,
            text=True,
            timeout=5
        )
        
        if result.returncode == 0 and result.stdout.strip():
            container_id = result.stdout.strip().split('\n')[0]
            # Obtém o nome do container pelo ID
            name_result = subprocess.run(
                ["docker", "inspect", "--format", "{{.Name}}", container_id],
                capture_output=True,
                text=True,
                timeout=5
            )
            if name_result.returncode == 0 and name_result.stdout.strip():
                container_name = name_result.stdout.strip().lstrip('/')
                return container_name
        
        # Fallback: Lista todos os containers rodando e procura
        result = subprocess.run(
            ["docker", "ps", "--format", "{{.Names}}"],
            capture_output=True,
            text=True,
            timeout=5
        )
        
        if result.returncode == 0 and result.stdout.strip():
            containers = result.stdout.strip().split('\n')
            
            # Procura por diferentes padrões de nome
            patterns = [
                service_name,  # Nome direto
                f"tcc2-rps-benchmark-{service_name}",  # Com prefixo do projeto
                f"{service_name}-1",  # Com sufixo -1
                f"tcc2-rps-benchmark-{service_name}-1",  # Com prefixo e sufixo
            ]
            
            for container in containers:
                container = container.strip()
                for pattern in patterns:
                    if pattern in container:
                        return container
            
            # Se não encontrou por padrão, procura por substring
            for container in containers:
                container = container.strip()
                # Remove prefixos comuns e compara
                clean_name = container.replace('tcc2-rps-benchmark-', '').replace('-1', '')
                if clean_name == service_name or service_name in container:
                    return container
        
        return None
    except Exception as e:
        return None

def get_container_stats(container_name_or_service):
    """Obtém estatísticas de CPU e memória de um container"""
    try:
        # Se não encontrar pelo nome direto, tenta buscar pelo serviço
        container_name = container_name_or_service
        if not container_name.startswith('tcc2-rps-benchmark-') and not container_name == 'benchmark_server':
            found_name = get_container_name_by_service(container_name_or_service)
            if found_name:
                container_name = found_name
        
        # Obtém stats do container específico
        stats_result = subprocess.run(
            ["docker", "stats", "--no-stream", "--format", 
             "{{.CPUPerc}}\t{{.MemUsage}}\t{{.MemPerc}}", container_name],
            capture_output=True,
            text=True,
            timeout=5
        )
        
        if stats_result.returncode != 0 or not stats_result.stdout.strip():
            return None
        
        parts = stats_result.stdout.strip().split('\t')
        if len(parts) < 3:
            return None
        
        cpu_perc = parts[0].rstrip('%')
        mem_usage = parts[1]  # e.g., "123.45MiB / 2GiB"
        mem_perc = parts[2].rstrip('%')
        
        # Parse memory usage
        mem_parts = mem_usage.split(' / ')
        if len(mem_parts) == 2:
            mem_used_str = mem_parts[0]
            mem_total_str = mem_parts[1]
            
            # Convert to MB
            def parse_memory(mem_str):
                mem_str = mem_str.strip()
                if 'GiB' in mem_str:
                    return float(mem_str.replace('GiB', '').strip()) * 1024
                elif 'MiB' in mem_str:
                    return float(mem_str.replace('MiB', '').strip())
                elif 'KiB' in mem_str:
                    return float(mem_str.replace('KiB', '').strip()) / 1024
                elif 'B' in mem_str:
                    return float(mem_str.replace('B', '').strip()) / (1024 * 1024)
                return 0.0
            
            mem_used_mb = parse_memory(mem_used_str)
            mem_total_mb = parse_memory(mem_total_str)
        else:
            mem_used_mb = 0.0
            mem_total_mb = 0.0
        
        return {
            'cpu_percent': float(cpu_perc) if cpu_perc else 0.0,
            'memory_used_mb': mem_used_mb,
            'memory_total_mb': mem_total_mb,
            'memory_percent': float(mem_perc) if mem_perc else 0.0
        }
    except Exception as e:
        return None

def monitor_containers(client_service_name, server_container_name, duration, stats_data, stop_event):
    """Monitora containers durante a execução do teste"""
    start_time = time.time()
    end_time = start_time + duration + 120  # Monitora por duration + buffer maior
    
    client_stats = []
    server_stats = []
    consecutive_failures = 0
    max_consecutive_failures = 30  # Aguarda mais tempo para container aparecer
    
    # Aguarda container do cliente aparecer
    client_container_name = None
    wait_start = time.time()
    while time.time() - wait_start < 30:  # Aguarda até 30 segundos
        found_name = get_container_name_by_service(client_service_name)
        if found_name:
            client_container_name = found_name
            print(f"Found client container: {client_container_name}")
            break
        time.sleep(1)
    
    if not client_container_name:
        print(f"Warning: Could not find client container for {client_service_name}")
    
    # Monitora enquanto o teste está rodando
    while not stop_event.is_set() and time.time() < end_time:
        # Stats do cliente
        if client_container_name:
            client_stat = get_container_stats(client_container_name)
            if client_stat:
                client_stats.append(client_stat)
                consecutive_failures = 0
            else:
                consecutive_failures += 1
        else:
            # Tenta encontrar novamente
            found_name = get_container_name_by_service(client_service_name)
            if found_name:
                client_container_name = found_name
                print(f"Found client container (retry): {client_container_name}")
        
        # Stats do servidor
        server_stat = get_container_stats(server_container_name)
        if server_stat:
            server_stats.append(server_stat)
        
        # Se não conseguir obter stats do cliente por muito tempo e já coletou dados, pode ter terminado
        if consecutive_failures >= max_consecutive_failures and len(client_stats) > 10:
            break
        
        time.sleep(2)  # Coleta stats a cada 2 segundos
    
    # Calcula médias
    def calculate_averages(stats_list):
        if not stats_list:
            return {
                'cpu_percent_avg': 0.0,
                'memory_used_mb_avg': 0.0,
                'memory_total_mb_avg': 0.0,
                'memory_percent_avg': 0.0
            }
        
        return {
            'cpu_percent_avg': sum(s['cpu_percent'] for s in stats_list) / len(stats_list),
            'memory_used_mb_avg': sum(s['memory_used_mb'] for s in stats_list) / len(stats_list),
            'memory_total_mb_avg': sum(s['memory_total_mb'] for s in stats_list) / len(stats_list) if stats_list else 0.0,
            'memory_percent_avg': sum(s['memory_percent'] for s in stats_list) / len(stats_list)
        }
    
    stats_data['client'] = calculate_averages(client_stats)
    stats_data['server'] = calculate_averages(server_stats)
    
    # Log para debug
    print(f"Monitoring completed: Client samples={len(client_stats)}, Server samples={len(server_stats)}")
    if len(client_stats) == 0:
        print(f"Warning: No client stats collected for {client_service_name}")
    if len(server_stats) == 0:
        print(f"Warning: No server stats collected")

def run_single_test(library, concurrency):
    """Executa um teste individual"""
    print(f"\n{'='*80}")
    print(f"Testing: {library} with concurrency {concurrency}")
    print(f"{'='*80}\n")
    
    service_name = f"client_{library}_{concurrency}"
    client_container_name = service_name  # Será resolvido dinamicamente
    server_container_name = "benchmark_server"
    
    # Inicia o servidor se não estiver rodando (com retry)
    if not start_server_with_retry():
        print(f"Error: Could not start server for {library}_c{concurrency}")
        return False, {}
    
    # Aguarda servidor estar completamente pronto
    if not wait_for_server(max_wait=15):
        print(f"Warning: Server may not be ready for {library}_c{concurrency}")
    
    time.sleep(2)  # Buffer adicional
    
    # Dados para coletar stats
    stats_data = {}
    stop_event = threading.Event()
    
    # Inicia monitoramento em thread separada
    # Estimamos duração do teste (warmup 120s + test 180s + buffer)
    test_duration = 120 + 180 + 120  # ~7 minutos
    monitor_thread = threading.Thread(
        target=monitor_containers,
        args=(service_name, server_container_name, test_duration, stats_data, stop_event),
        daemon=False  # Não é daemon para garantir que termina corretamente
    )
    
    # Timeout aumentado para testes com alta concorrência (warmup 120s + test 180s + buffer)
    # Para c128 e c512, pode demorar mais devido ao overhead
    timeout_seconds = 900 if concurrency >= 128 else 600  # 15 min para alta concorrência, 10 min para baixa
    
    # Executa o teste e inicia monitoramento simultaneamente
    try:
        # Inicia monitoramento antes de iniciar o container do cliente
        monitor_thread.start()
        time.sleep(1)  # Pequeno delay para garantir que monitoramento está rodando
        
        subprocess.run(
            ["docker-compose", "up", "--abort-on-container-exit", service_name],
            check=True,
            timeout=timeout_seconds
        )
        test_success = True
    except subprocess.TimeoutExpired:
        print(f"Test {library}_c{concurrency} timed out after {timeout_seconds}s!")
        test_success = False
    except subprocess.CalledProcessError as e:
        print(f"Test {library}_c{concurrency} failed: {e}")
        if hasattr(e, 'stdout') and e.stdout:
            print(f"  stdout: {e.stdout[:500]}")  # Primeiros 500 chars
        if hasattr(e, 'stderr') and e.stderr:
            print(f"  stderr: {e.stderr[:500]}")  # Primeiros 500 chars
        test_success = False
    finally:
        # Sinaliza para thread parar e aguarda
        stop_event.set()
        monitor_thread.join(timeout=30)  # Aguarda até 30 segundos para thread terminar
    
    # Atualiza arquivo JSON de resultados com stats (mesmo se teste falhou)
    script_dir = Path(__file__).parent
    results_dir = script_dir.parent / "results"
    result_file = results_dir / f"{library}_c{concurrency}.json"
    
    if result_file.exists():
        try:
            with open(result_file, 'r') as f:
                result_data = json.load(f)
            
            # Adiciona métricas de recursos (garante estrutura mesmo se vazia)
            if not stats_data:
                stats_data = {
                    'client': {
                        'cpu_percent_avg': 0.0,
                        'memory_used_mb_avg': 0.0,
                        'memory_total_mb_avg': 0.0,
                        'memory_percent_avg': 0.0
                    },
                    'server': {
                        'cpu_percent_avg': 0.0,
                        'memory_used_mb_avg': 0.0,
                        'memory_total_mb_avg': 0.0,
                        'memory_percent_avg': 0.0
                    }
                }
            
            result_data['resource_usage'] = stats_data
            
            with open(result_file, 'w') as f:
                json.dump(result_data, f, indent=2)
            
            print(f"Added resource metrics to {result_file.name}")
            if stats_data.get('client', {}).get('cpu_percent_avg', 0) == 0:
                print(f"  Warning: Resource metrics appear to be empty or zero")
        except Exception as e:
            print(f"Warning: Failed to update result file with resource metrics: {e}")
    
    # Limpa containers
    subprocess.run(["docker-compose", "down"], check=False)
    
    return test_success, stats_data

def collect_results():
    """Coleta todos os arquivos JSON de resultados"""
    # Get results directory relative to script location
    script_dir = Path(__file__).parent
    results_dir = script_dir.parent / "results"
    all_results = []
    
    if not results_dir.exists():
        print(f"Warning: Results directory {results_dir} does not exist")
        return all_results
    
    # Skip summary.json itself
    for json_file in sorted(results_dir.glob("*.json")):
        if json_file.name == "summary.json":
            continue
            
        try:
            with open(json_file, 'r') as f:
                data = json.load(f)
                # Only add valid results (must have library field)
                if isinstance(data, dict) and "library" in data:
                    all_results.append(data)
                else:
                    print(f"Warning: Skipping invalid result file {json_file.name}")
        except (json.JSONDecodeError, IOError) as e:
            print(f"Warning: Failed to read {json_file.name}: {e}")
    
    return all_results

def generate_summary_report(results):
    """Gera relatório consolidado"""
    script_dir = Path(__file__).parent
    summary_path = script_dir.parent / "results" / "summary.json"
    summary_path.parent.mkdir(exist_ok=True)
    
    with open(summary_path, 'w') as f:
        json.dump(results, f, indent=2)
    
    print(f"\nSummary saved to {summary_path}")
    print(f"Total results collected: {len(results)}")

def main():
    # Limpa resultados anteriores
    script_dir = Path(__file__).parent
    results_dir = script_dir.parent / "results"
    results_dir.mkdir(exist_ok=True)
    
    for old_file in results_dir.glob("*.json"):
        if old_file.name != "summary.json":  # Keep summary.json
            old_file.unlink()
    
    # Build das imagens
    print("Building Docker images...")
    subprocess.run(["docker-compose", "build"], check=True)
    
    # Executa todos os testes
    total_tests = len(LIBRARIES) * len(CONCURRENCY_LEVELS)
    completed = 0
    
    for library in LIBRARIES:
        for concurrency in CONCURRENCY_LEVELS:
            completed += 1
            print(f"\n[{completed}/{total_tests}] Running test...")
            
            success, stats = run_single_test(library, concurrency)
            
            if not success:
                print(f"Warning: Test {library}_c{concurrency} did not complete successfully")
            elif stats:
                print(f"Resource usage - Client CPU: {stats.get('client', {}).get('cpu_percent_avg', 0):.2f}%, "
                      f"Memory: {stats.get('client', {}).get('memory_used_mb_avg', 0):.2f}MB | "
                      f"Server CPU: {stats.get('server', {}).get('cpu_percent_avg', 0):.2f}%, "
                      f"Memory: {stats.get('server', {}).get('memory_used_mb_avg', 0):.2f}MB")
            
            # Pausa entre testes
            time.sleep(10)
    
    # Coleta e consolida resultados
    print("\nCollecting results...")
    all_results = collect_results()
    
    generate_summary_report(all_results)
    
    print("\n" + "="*80)
    print("Benchmark completed!")
    print(f"Total tests: {total_tests}")
    print(f"Results saved in: {results_dir.absolute()}")
    print("="*80)

if __name__ == "__main__":
    main()

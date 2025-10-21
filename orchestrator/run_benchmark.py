# orchestrator/run_benchmark.py
#!/usr/bin/env python3
import subprocess
import time
import json
import os
from pathlib import Path

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

def run_single_test(library, concurrency):
    """Executa um teste individual"""
    print(f"\n{'='*80}")
    print(f"Testing: {library} with concurrency {concurrency}")
    print(f"{'='*80}\n")
    
    service_name = f"client_{library}_{concurrency}"
    
    # Inicia o servidor se não estiver rodando
    subprocess.run(["docker-compose", "up", "-d", "server"], check=True)
    time.sleep(5)  # Aguarda servidor inicializar
    
    # Executa o teste
    try:
        subprocess.run(
            ["docker-compose", "up", "--abort-on-container-exit", service_name],
            check=True,
            timeout=600  # 10 minutos de timeout
        )
    except subprocess.TimeoutExpired:
        print(f"Test {library}_c{concurrency} timed out!")
        return False
    except subprocess.CalledProcessError as e:
        print(f"Test {library}_c{concurrency} failed: {e}")
        return False
    
    # Limpa containers
    subprocess.run(["docker-compose", "down"], check=False)
    
    return True

def collect_results():
    """Coleta todos os arquivos JSON de resultados"""
    results_dir = Path("../results")
    all_results = []
    
    for json_file in results_dir.glob("*.json"):
        with open(json_file, 'r') as f:
            all_results.append(json.load(f))
    
    return all_results

def generate_summary_report(results):
    """Gera relatório consolidado"""
    summary_path = Path("./results/summary.json")
    
    with open(summary_path, 'w') as f:
        json.dump(results, f, indent=2)
    
    print(f"\nSummary saved to {summary_path}")

def main():
    # Limpa resultados anteriores
    results_dir = Path("./results")
    results_dir.mkdir(exist_ok=True)
    
    for old_file in results_dir.glob("*.json"):
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
            
            success = run_single_test(library, concurrency)
            
            if not success:
                print(f"Warning: Test {library}_c{concurrency} did not complete successfully")
            
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

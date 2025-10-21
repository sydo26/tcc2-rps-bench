#!/usr/bin/env python3
import json
import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns
from pathlib import Path

def load_results():
    """Carrega o summary.json"""
    with open("./results/summary.json", 'r') as f:
        results = json.load(f)
    return pd.DataFrame(results)

def generate_comparison_table(df):
    """Gera tabela comparativa em Markdown"""
    table_path = Path("./results/comparison_table.md")
    # Agrupa por biblioteca e concorrência
    pivot_throughput = df.pivot_table(
        values='throughput',
        index='library',
        columns='concurrency',
        aggfunc='mean'
    )
    pivot_latency_p95 = df.pivot_table(
        values='latency_p95_ms',
        index='library',
        columns='concurrency',
        aggfunc='mean'
    )
    with open(table_path, 'w') as f:
        f.write("# HTTP Libraries Benchmark Results\n\n")
        
        f.write("## Throughput (req/s)\n\n")
        f.write(pivot_throughput.to_markdown())
        f.write("\n\n")
        
        f.write("## Latency P95 (ms)\n\n")
        f.write(pivot_latency_p95.to_markdown())
        f.write("\n\n")
    
    print(f"Comparison table saved to {table_path}")

def generate_charts(df):
    """Gera gráficos comparativos"""
    sns.set_style("whitegrid")
    
    # Gráfico 1: Throughput por biblioteca e concorrência
    plt.figure(figsize=(14, 8))
    sns.barplot(data=df, x='library', y='throughput', hue='concurrency')
    plt.title('Throughput Comparison by Library and Concurrency')
    plt.xlabel('Library')
    plt.ylabel('Throughput (req/s)')
    plt.xticks(rotation=45)
    plt.legend(title='Concurrency')
    plt.tight_layout()
    plt.savefig('./results/chart_throughput.png', dpi=300)
    print("Chart saved: chart_throughput.png")
    
    # Gráfico 2: Latência P95
    plt.figure(figsize=(14, 8))
    sns.barplot(data=df, x='library', y='latency_p95_ms', hue='concurrency')
    plt.title('P95 Latency Comparison by Library and Concurrency')
    plt.xlabel('Library')
    plt.ylabel('Latency P95 (ms)')
    plt.xticks(rotation=45)
    plt.legend(title='Concurrency')
    plt.tight_layout()
    plt.savefig('./results/chart_latency_p95.png', dpi=300)
    print("Chart saved: chart_latency_p95.png")
    
    # Gráfico 3: Error Rate
    plt.figure(figsize=(14, 8))
    sns.barplot(data=df, x='library', y='error_rate', hue='concurrency')
    plt.title('Error Rate by Library and Concurrency')
    plt.xlabel('Library')
    plt.ylabel('Error Rate (%)')
    plt.xticks(rotation=45)
    plt.legend(title='Concurrency')
    plt.tight_layout()
    plt.savefig('./results/chart_error_rate.png', dpi=300)
    print("Chart saved: chart_error_rate.png")
    
    # Gráfico 4: Boxplot de latências por linguagem
    plt.figure(figsize=(14, 8))
    df_melted = df.melt(
        id_vars=['library', 'language', 'concurrency'],
        value_vars=['latency_avg_ms', 'latency_p50_ms', 'latency_p95_ms', 'latency_p99_ms'],
        var_name='metric',
        value_name='latency'
    )
    sns.boxplot(data=df_melted, x='language', y='latency', hue='metric')
    plt.title('Latency Distribution by Language')
    plt.xlabel('Language')
    plt.ylabel('Latency (ms)')
    plt.legend(title='Metric')
    plt.tight_layout()
    plt.savefig('./results/chart_latency_distribution.png', dpi=300)
    print("Chart saved: chart_latency_distribution.png")

def generate_csv_export(df):
    """Exporta resultados para CSV"""
    csv_path = Path("./results/benchmark_results.csv")
    df.to_csv(csv_path, index=False)
    print(f"CSV export saved to {csv_path}")

if __name__ == "__main__":
    print("Generating benchmark report...\n")
    
    df = load_results()
    
    print(f"Loaded {len(df)} test results\n")
    
    generate_comparison_table(df)
    generate_charts(df)
    generate_csv_export(df)
    
    print("\n" + "="*80)
    print("Report generation completed!")
    print("Check the ./results directory for all outputs")
    print("="*80)
# Plano Técnico Detalhado: Benchmark de Bibliotecas HTTP

Vou propor uma **reestruturação completa** do seu projeto, mantendo o foco em **bibliotecas HTTP** (não frameworks), com metodologia rigorosa e resultados reprodutíveis.

---

## 📋 Arquitetura Proposta

### Estrutura de Diretórios
```
benchmark-http-libs/
├── server/
│   ├── server.go
│   ├── Dockerfile
│   └── go.mod
├── clients/
│   ├── python/
│   │   ├── client_requests.py
│   │   ├── client_httpx.py
│   │   ├── requirements.txt
│   │   └── Dockerfile
│   ├── javascript/
│   │   ├── client_axios.js
│   │   ├── client_undici.js
│   │   ├── package.json
│   │   └── Dockerfile
│   ├── go/
│   │   ├── client_nethttp.go
│   │   ├── client_fasthttp.go
│   │   ├── go.mod
│   │   └── Dockerfile
│   └── elixir/
│       ├── client_httpoison.exs
│       ├── client_finch.exs
│       └── Dockerfile
├── orchestrator/
│   ├── run_benchmark.py
│   ├── metrics_collector.py
│   ├── report_generator.py
│   └── requirements.txt
├── results/
│   └── (gerado automaticamente)
├── docker-compose.yml
└── README.md
```

---

## 🎯 Metodologia de Teste

### Fase 1: Warm-up (2 minutos)
- Estabilização do servidor
- Aquecimento de caches
- **Não coleta métricas**

### Fase 2: Execução (3 minutos)
- Coleta de métricas detalhadas
- Medição de latência, throughput e erros

### Níveis de Concorrência
Cada biblioteca será testada com: **8, 32, 128 e 512** conexões simultâneas

### Métricas Coletadas
- **Throughput**: requisições/segundo
- **Latência**: média, p50, p95, p99
- **Taxa de erros**: % de requisições falhadas
- **Recursos**: CPU e memória (média e pico)

---

## 📊 Como Executar

### 1. Teste Individual (uma biblioteca, uma concorrência)

```bash
# Exemplo: testar requests com concorrência 8
docker-compose up server client_requests_8
```

### 2. Execução Completa Automatizada

```bash
# Instalar dependências do orchestrator
cd orchestrator
pip install -r requirements.txt

# Executar todos os testes
python run_benchmark.py

# Gerar relatórios
python report_generator.py
```

### 3. Estrutura de Resultados Gerados

```
results/
├── requests_c8.json
├── requests_c32.json
├── httpx_c8.json
├── undici_c8.json
├── ...
├── summary.json
├── comparison_table.md
├── benchmark_results.csv
├── chart_throughput.png
├── chart_latency_p95.png
├── chart_error_rate.png
└── chart_latency_distribution.png
```

---

## 🎯 Principais Melhorias Implementadas

### ✅ Concorrência Real
- Cada cliente implementa concorrência apropriada para sua linguagem
- Python: ThreadPoolExecutor (requests) e asyncio (httpx)
- JavaScript: Promise.all com workers
- Go: Goroutines
- Elixir: Processos Erlang

### ✅ Metodologia Rigorosa
- Warm-up de 2 minutos (configurável)
- Execução de 3 minutos (configurável)
- 4 níveis de concorrência: 8, 32, 128, 512

### ✅ Métricas Completas
- Throughput (req/s)
- Latência: média, p50, p95, p99, min, max
- Taxa de erros (%)
- Total de requisições bem-sucedidas/falhadas

### ✅ Recursos Balanceados
- Limites de CPU e memória via Docker deploy
- Todos os clientes: 1 CPU, 512MB RAM
- Servidor: 2 CPUs, 2GB RAM
- Isolamento via cgroups do Docker

### ✅ Automação Completa
- Orquestrador Python executa todos os testes sequencialmente
- Geração automática de relatórios
- Exportação em múltiplos formatos (JSON, CSV, Markdown)
- Gráficos comparativos

### ✅ Reprodutibilidade
- Configuração via variáveis de ambiente
- Docker garante ambiente consistente
- Resultados salvos em JSON estruturado
- Documentação completa

---

## 📈 Exemplo de Saída

```json
{
  "library": "undici",
  "language": "javascript",
  "concurrency": 8,
  "duration": 180,
  "total_requests": 145823,
  "successful_requests": 145820,
  "failed_requests": 3,
  "error_rate": 0.002,
  "throughput": 810.13,
  "latency_avg_ms": 9.87,
  "latency_p50_ms": 8.45,
  "latency_p95_ms": 15.32,
  "latency_p99_ms": 22.18,
  "latency_min_ms": 2.14,
  "latency_max_ms": 145.67
}
```

---

## 🔧 Personalização

### Ajustar Duração dos Testes

Edite as variáveis de ambiente no `docker-compose.yml`:

```yaml
environment:
  - WARMUP_DURATION=60    # Reduzir para testes rápidos
  - TEST_DURATION=300     # Aumentar para maior precisão
```

### Adicionar Mais Níveis de Concorrência

Adicione novos serviços ao `docker-compose.yml` e atualize `CONCURRENCY_LEVELS` no orchestrator.

### Limitar Recursos

Ajuste os limites em `deploy.resources` conforme necessário.

# clients/go/Dockerfile (versão ultra-explícita)
FROM golang:1.21-alpine AS builder

WORKDIR /app

# Instala dependências do sistema se necessário
RUN apk add --no-cache git

# Inicializa o módulo
COPY go.mod ./

# Copia os arquivos fonte
COPY client_nethttp.go client_fasthttp.go ./

# Baixa a dependência específica do fasthttp
RUN go get github.com/valyala/fasthttp@v1.51.0

# Atualiza go.mod e go.sum
RUN go mod tidy

# Verifica dependências
RUN go mod verify

# Compila os binários
RUN CGO_ENABLED=0 GOOS=linux go build -a -installsuffix cgo -o client_nethttp client_nethttp.go
RUN CGO_ENABLED=0 GOOS=linux go build -a -installsuffix cgo -o client_fasthttp client_fasthttp.go

# Imagem final
FROM alpine:latest

RUN apk --no-cache add ca-certificates

WORKDIR /app

COPY --from=builder /app/client_nethttp /app/client_fasthttp ./

CMD ["./client_nethttp"]

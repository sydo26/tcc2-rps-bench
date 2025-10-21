# server/Dockerfile
FROM golang:1.21-alpine

WORKDIR /app
COPY server.go .
COPY go.mod* ./

RUN go mod init server 2>/dev/null || true
RUN go mod tidy
RUN go build -o server server.go

EXPOSE 8080

CMD ["./server"]
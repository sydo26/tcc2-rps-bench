# clients/elixir/Dockerfile
FROM elixir:1.15-alpine

WORKDIR /app

RUN mix local.hex --force && mix local.rebar --force

COPY client_httpoison.exs client_finch.exs ./

# Será especificado qual script rodar via command no docker-compose
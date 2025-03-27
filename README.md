# Apache Airflow com Docker Compose

Este guia fornece instruções para configurar o Apache Airflow usando Docker Compose.

## Pré-requisitos

- Docker
- Docker Compose
- Git
- Pelo menos 4GB de RAM disponível

## Instalação

1. Crie um diretório para o projeto:
```bash
mkdir airflow
cd airflow
```

2. Inicie os serviços:
```bash
docker compose up -d
```

### Configuração de Permissões

#### Defina as permissões no host do socket do Docker
```bash
sudo chmod 666 /var/run/docker.sock
```

#### Configurando as permissões na reinicialização do sistema
Essas permissões permitem que o Airflow execute o Docker:
```bash
sudo crontab -e
@reboot chmod 666 /var/run/docker.sock
```

## Acessando o Airflow

- URL: `http://localhost:8081`
- Usuário padrão: `airflow`
- Senha padrão: `airflow`

## Comandos Úteis

```bash
# Parar todos os serviços
docker compose down

# Executar comandos CLI do Airflow
docker compose run airflow-worker airflow [comando]

# Limpar volumes e contêineres (cuidado: apaga dados)
docker compose down --volumes --remove-orphans
```

## Estrutura de Diretórios

- `./dags`: Diretório para seus arquivos DAG
- `./logs`: Logs do Airflow
- `./plugins`: Plugins personalizados
- `./config`: Arquivos de configuração

## Observações Importantes

- O ambiente inclui exemplos de DAGs por padrão.
- Para desativar DAGs de exemplo, defina `AIRFLOW__CORE__LOAD_EXAMPLES=false` no arquivo `.env`.
- Recomenda-se não usar este setup em produção sem configurações adicionais de segurança.
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
mkdir airflow-docker
cd airflow-docker
```

2. Baixe o arquivo docker-compose.yaml:
```bash
curl -LfO 'https://airflow.apache.org/docs/apache-airflow/2.10.4/docker-compose.yaml'
```

3. Configure o acesso ao socket do Docker:
```yaml
volumes:
    - /var/run/docker.sock:/var/run/docker.sock:rw
```

4. Crie os diretórios necessários:
```bash
mkdir -p ./dags ./logs ./plugins ./config
```

5. Configure e crie o arquivo do ambiente:
```bash
echo -e "AIRFLOW_UID=$(id -u)" > .env
```

6. Inicialize o banco de dados:
```bash
docker compose up airflow-init
```

7. Inicie os serviços:
```bash
docker compose up -d
```

### Defina as permissões no host do socket do Docker
# Essa 
```bash
sudo chmod 666 /var/run/docker.sock
```

### Configurando as permissões na reinicialização do sistema
Essas permissões permitem que o airflow execute o docker
```bash
sudo crontab -e
@reboot chmod 666 /var/run/docker.sock
```

## Acessando o Airflow

- URL: `http://localhost:8080`
- Usuário padrão: `airflow`
- Senha padrão: `airflow`

## Comandos Úteis

```bash
# Parar todos os serviços
docker compose down

# Verificar logs
docker compose logs

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

- O ambiente inclui exemplos de DAGs por padrão
- Para desativar DAGs de exemplo, defina `AIRFLOW__CORE__LOAD_EXAMPLES=false` no arquivo .env
- Recomenda-se não usar este setup em produção sem configurações adicionais de segurança
from datetime import datetime, timedelta
import os
import shutil
import requests
import pandas as pd
from airflow import DAG
from airflow.operators.python import PythonOperator
from airflow.providers.postgres.operators.postgres import PostgresOperator
from airflow.providers.postgres.hooks.postgres import PostgresHook
from airflow.models import Variable
import logging
from psycopg2.extras import execute_values
from datetime import datetime


# Configurações padrão do DAG
default_args = {
    "owner": "diogo.sousa",
    "depends_on_past": False,
    "start_date": datetime(datetime.now().year, 1, 1),
    "email_on_failure": False,
    "email_on_retry": False,
    "retries": 1,
    "retry_delay": timedelta(minutes=5),
}

# Definição do DAG
dag = DAG(
    "inpe_queimadas_bahia_mensal",
    default_args=default_args,
    description="Download e carga de dados de queimadas da Bahia - INPE",
    schedule_interval="@monthly",  # Executa mensalmente
    catchup=True,
    max_active_runs=5,
    tags=["bahia_sem_fogo", "inpe", "focos_calor"],
)

# Configurações
BASE_URL = (
    "https://dataserver-coids.inpe.br/queimadas/queimadas/focos/csv/mensal/Brasil/"
)
DATA_DIR = "/tmp/queimadas_data"
POSTGRES_CONN_ID = "foco_calor"  # Configure sua conexão no Airflow
TABLE_NAME = "foco_calor"
ESTADO = "BAHIA"  # Estado a ser filtrado, em caixa alta


def mes_execucao_dag(**context):
    ds_nodash = context["ds_nodash"][0:6]  # string '20250915'
    return ds_nodash


def create_tmp_data_directory():
    """Cria o diretório temporário para os dados"""
    if not os.path.exists(DATA_DIR):
        os.makedirs(DATA_DIR)
    logging.info(f"Diretório {DATA_DIR} criado/verificado")


def download_and_extract_data(**context):
    """
    Faz o download dos arquivos zip e extrai os CSVs
    """
    month = mes_execucao_dag(**context)

    filename = f"focos_mensal_br_{month}.csv"
    url = f"{BASE_URL}{filename}"
    file_path = os.path.join(DATA_DIR, filename)

    logging.info(f"Preparando para baixar dados do mês: {url}")

    try:
        logging.info(f"Baixando arquivo de {month}: {url}")

        # Download do arquivo
        response = requests.get(url, timeout=300)
        response.raise_for_status()

        # Salva o arquivo zip
        with open(file_path, "wb") as f:
            f.write(response.content)

        logging.info(f"Arquivo {filename} baixado com sucesso")

    except requests.exceptions.RequestException as e:
        logging.warning(f"Erro ao baixar arquivo para o ano {month}: {e}")

    # Armazena a lista de arquivos no XCom para a próxima task
    extracted_files = [file_path]
    context["task_instance"].xcom_push(key="extracted_files", value=extracted_files)
    logging.info(f"Total de {len(extracted_files)} arquivos processados")


def test_postgres_connection():
    try:
        hook = PostgresHook(postgres_conn_id=POSTGRES_CONN_ID)
        conn = hook.get_conn()

        if conn and not conn.closed:  # conn.closed == 0 significa aberta
            logging.info("✅ Conexão estabelecida com o PostgreSQL.")
        else:
            logging.error("❌ Falha ao abrir conexão com o PostgreSQL.")

        # Testa um SELECT simples
        cursor = conn.cursor()
        cursor.execute("SELECT 1;")
        result = cursor.fetchone()
        logging.info(f"Teste SELECT 1 retornou: {result}")

        cursor.close()
        conn.close()

    except Exception as e:
        logging.error(f"❌ Erro ao conectar no PostgreSQL: {e}")


def load_data_to_postgres(**context):
    """
    Carrega todos os CSVs no PostgreSQL, criando coluna geométrica a partir de latitude e longitude.
    Apenas campos específicos são carregados.
    """
    extracted_files = context["task_instance"].xcom_pull(key="extracted_files")

    logging.info(f"Processando arquivo: {extracted_files}")

    if not extracted_files or len(extracted_files) == 0:
        logging.warning("Nenhum arquivo foi processado")
        return

    postgres_hook = PostgresHook(postgres_conn_id=POSTGRES_CONN_ID)
    conn = postgres_hook.get_conn()
    cursor = conn.cursor()

    total_records = 0

    month = mes_execucao_dag(**context)

    file_name = f"focos_mensal_br_{month}.csv"
    file_path = os.path.join(DATA_DIR, file_name)

    logging.info(f"Carregando CSV {file_name}: {file_path}")

    try:
        # Lê o CSV com fallback de encoding
        try:
            df = pd.read_csv(file_path, encoding="utf-8")
        except UnicodeDecodeError:
            try:
                df = pd.read_csv(file_path, encoding="latin1")
            except UnicodeDecodeError:
                df = pd.read_csv(file_path, encoding="cp1252")

        logging.info(
            f"CSV {file_name} lido com sucesso. Colunas: {list(df.columns)} | Registros: {len(df)}"
        )

        # Converte data_pas
        df["data"] = pd.to_datetime(df["data_hora_gmt"], errors="coerce")

        # Colunas esperadas
        expected_columns = [
            "lat",
            "lon",
            "data",
            "satelite",
            "municipio",
            "estado",
            "pais",
            "bioma",
        ]

        missing_columns = [col for col in expected_columns if col not in df.columns]
        if missing_columns:
            logging.error(f"Colunas ausentes no CSV {file_name}: {missing_columns}")

        # Seleção e filtro
        df = df[expected_columns].copy()
        df = df[df["estado"] == ESTADO]

        if df.empty:
            logging.warning(f"Nenhum registro da Bahia encontrado no ano {file_name}")

        # Remove registros inválidos
        initial_count = len(df)
        df = df.dropna(subset=["lat", "lon", "data"])
        final_count = len(df)
        if initial_count != final_count:
            logging.warning(
                f"Arquivo {file_name}: removidos {initial_count - final_count} registros nulos"
            )

        if df.empty:
            logging.warning(f"Arquivo {file_name}: nenhum registro válido após limpeza")

        # Geometria
        df["geom"] = df.apply(
            lambda r: f"SRID=4326;POINT({r['lon']} {r['lat']})", axis=1
        )

        # df.rename(columns={"data_pas": "data"}, inplace=True)

        # Preparação para INSERT
        records = df.values.tolist()
        columns = list(df.columns)

        insert_query = f"""
            INSERT INTO {TABLE_NAME} ({", ".join(columns)})
            VALUES %s
            ON CONFLICT (lat, lon, data) DO NOTHING;
        """

        execute_values(
            cursor,
            insert_query,
            records,
            template=f"({', '.join(['%s'] * (len(columns) - 1))}, ST_GeomFromText(%s))",
            page_size=1000,
        )

        total_records += len(records)
        conn.commit()

        logging.info(f"Arquivo {file_name}: {len(records)} registros carregados")

        # Remove CSV após processar
        os.remove(file_path)

    except Exception as e:
        logging.error(f"Erro ao processar ano {file_name}: {e}")

    cursor.close()
    conn.close()

    logging.info(f"✅ Total de registros carregados: {total_records}")


def cleanup_data_directory():
    """Remove diretório temporário e todo o conteúdo"""
    try:
        if DATA_DIR.exists() and DATA_DIR.is_dir():
            shutil.rmtree(DATA_DIR)
            logging.info("Limpeza do diretório temporário concluída")
        else:
            logging.info(f"Diretório {DATA_DIR} não existe ou não é um diretório")
    except Exception as e:
        logging.warning(f"Erro na limpeza: {e}")


# Definição das tasks
create_dir_task = PythonOperator(
    task_id="create_data_directory", python_callable=create_tmp_data_directory, dag=dag
)

test_connection_postgres_task = PythonOperator(
    task_id="test_postgres_connection",
    python_callable=test_postgres_connection,
    dag=dag,
)

download_extract_task = PythonOperator(
    task_id="download_and_extract_data",
    python_callable=download_and_extract_data,
    dag=dag,
)

load_data_task = PythonOperator(
    task_id="load_data_to_postgres", python_callable=load_data_to_postgres, dag=dag
)

cleanup_task = PythonOperator(
    task_id="cleanup_data_directory",
    python_callable=cleanup_data_directory,
    dag=dag,
    trigger_rule="all_done",  # Executa independente do status das tasks anteriores
)


(
    [create_dir_task >> download_extract_task, test_connection_postgres_task]
    >> load_data_task
    # >> cleanup_task
)

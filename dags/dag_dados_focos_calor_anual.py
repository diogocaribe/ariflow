from datetime import datetime, timedelta
from glob import glob
import os
import zipfile
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
    "start_date": datetime(2024, 1, 1),
    "email_on_failure": False,
    "email_on_retry": False,
    "retries": 1,
    "retry_delay": timedelta(minutes=5),
}

# Definição do DAG
dag = DAG(
    "inpe_queimadas_bahia_anual",
    default_args=default_args,
    description="Download e carga de dados de focos de calor da Bahia das tabelas anuais - INPE",
    catchup=False,
    max_active_runs=1,
    tags=["bahia_sem_fogo", "focos_calor", "bahia"],
)

# Configurações
BASE_URL = "https://dataserver-coids.inpe.br/queimadas/queimadas/focos/csv/anual/Brasil_todos_sats/"
DATA_DIR = "/tmp/queimadas_data"
POSTGRES_CONN_ID = "foco_calor"  # Configure sua conexão no Airflow
TABLE_NAME = "foco_calor"
FIRST_YEAR = 2003
LAST_YEAR = datetime.now().year  # Até o ano atual
ESTADO = "BAHIA"  # Estado a ser filtrado, em caixa alta


def create_tmp_data_directory():
    """Cria o diretório temporário para os dados"""
    if not os.path.exists(DATA_DIR):
        os.makedirs(DATA_DIR)
    logging.info(f"Diretório {DATA_DIR} criado/verificado")


def download_and_extract_data(**context):
    """
    Faz o download dos arquivos zip e extrai os CSVs
    """
    # Anos a serem processados (2003 a 2024)
    years = range(FIRST_YEAR, LAST_YEAR)
    extracted_files = []

    for year in years:
        filename = f"focos_br_todos-sats_{year}.zip"
        url = f"{BASE_URL}{filename}"
        zip_path = os.path.join(DATA_DIR, filename)

        try:
            logging.info(f"Baixando arquivo para o ano {year}: {url}")

            # Download do arquivo
            response = requests.get(url, timeout=300)
            response.raise_for_status()

            # Salva o arquivo zip
            with open(zip_path, "wb") as f:
                f.write(response.content)

            logging.info(f"Arquivo {filename} baixado com sucesso")

            # Extrai o arquivo zip
            csv_filename = f"focos_br_todos-sats_{year}.csv"
            csv_path = os.path.join(DATA_DIR, csv_filename)

            try:
                with zipfile.ZipFile(zip_path, "r") as zip_ref:
                    # lista todos os arquivos dentro do zip
                    members = zip_ref.namelist()

                    # procura o CSV (mesmo que esteja dentro de tmp/)
                    csv_in_zip = None
                    for member in members:
                        if member.endswith(csv_filename):
                            csv_in_zip = member
                            break

                    if csv_in_zip is None:
                        logging.warning(
                            f"Arquivo {csv_filename} não encontrado no zip {zip_path}"
                        )
                        continue

                    # extrai para o diretório destino
                    extracted_path = zip_ref.extract(csv_in_zip, DATA_DIR)

                    # renomeia para remover o "tmp/" do caminho, se existir
                    final_path = os.path.join(DATA_DIR, csv_filename)
                    if extracted_path != final_path:
                        os.rename(extracted_path, final_path)
            except KeyError:
                logging.warning(
                    f"Arquivo CSV {csv_filename} não encontrado no zip para o ano {year}"
                )

                csv_filename = f"focos_br_todos-sats_{year}.csv"
                with zipfile.ZipFile(zip_path, "r") as zip_ref:
                    zip_ref.extract(csv_filename, DATA_DIR)

            logging.info(f"Arquivo CSV {csv_filename} extraído com sucesso")

            # Remove o arquivo zip para economizar espaço
            os.remove(zip_path)

            extracted_files.append(
                {"year": year, "csv_path": csv_path, "filename": csv_filename}
            )

        except requests.exceptions.RequestException as e:
            logging.warning(f"Erro ao baixar arquivo para o ano {year}: {e}")
            continue
        except zipfile.BadZipFile as e:
            logging.warning(f"Erro ao extrair arquivo para o ano {year}: {e}")
            continue

    # Armazena a lista de arquivos no XCom para a próxima task
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

    logging.info(f"Arquivos extraídos: {extracted_files}")

    if not extracted_files or len(extracted_files) == 0:
        logging.warning("Nenhum arquivo foi processado")
        return

    postgres_hook = PostgresHook(postgres_conn_id=POSTGRES_CONN_ID)
    conn = postgres_hook.get_conn()
    cursor = conn.cursor()

    total_records = 0

    for file_info in extracted_files:
        csv_path = file_info["csv_path"]
        year = file_info["year"]
        logging.info(f"Carregando CSV do ano {year}: {csv_path}")

        try:
            # Lê o CSV com fallback de encoding
            try:
                df = pd.read_csv(csv_path, encoding="utf-8")
            except UnicodeDecodeError:
                try:
                    df = pd.read_csv(csv_path, encoding="latin1")
                except UnicodeDecodeError:
                    df = pd.read_csv(csv_path, encoding="cp1252")

            logging.info(
                f"CSV {year} lido com sucesso. Colunas: {list(df.columns)} | Registros: {len(df)}"
            )

            # Colunas esperadas
            expected_columns = [
                "latitude",
                "longitude",
                "data_pas",
                "satelite",
                "pais",
                "estado",
                "municipio",
                "bioma",
            ]

            missing_columns = [col for col in expected_columns if col not in df.columns]
            if missing_columns:
                logging.error(f"Colunas ausentes no CSV {year}: {missing_columns}")
                continue

            # Seleção e filtro
            df = df[expected_columns].copy()
            df = df[df["estado"] == ESTADO]

            if df.empty:
                logging.warning(f"Nenhum registro da Bahia encontrado no ano {year}")
                continue

            # Converte data_pas
            df["data_pas"] = pd.to_datetime(df["data_pas"], errors="coerce")

            # Remove registros inválidos
            initial_count = len(df)
            df = df.dropna(subset=["latitude", "longitude", "data_pas"])
            final_count = len(df)
            if initial_count != final_count:
                logging.warning(
                    f"Ano {year}: removidos {initial_count - final_count} registros nulos"
                )

            if df.empty:
                logging.warning(f"Ano {year}: nenhum registro válido após limpeza")
                continue

            # Geometria
            df["geom"] = df.apply(
                lambda r: f"SRID=4326;POINT({r['longitude']} {r['latitude']})", axis=1
            )

            df.rename(columns={
                "latitude": "lat", "longitude": "lon", 
                "data_pas": "data"}, inplace=True)

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

            logging.info(f"Ano {year}: {len(records)} registros carregados")

            # Remove CSV após processar
            os.remove(csv_path)

        except Exception as e:
            logging.error(f"Erro ao processar ano {year}: {e}")
            continue

    cursor.close()
    conn.close()

    logging.info(f"✅ Total de registros carregados: {total_records}")


def cleanup_data_directory():
    """Remove arquivos temporários"""
    try:
        for file in os.listdir(DATA_DIR):
            file_path = os.path.join(DATA_DIR, file)
            if os.path.isfile(file_path):
                os.remove(file_path)
        os.rmdir(DATA_DIR)
        logging.info("Limpeza do diretório temporário concluída")
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

drop_table_task = PostgresOperator(
    task_id="drop_postgres_table",
    postgres_conn_id=POSTGRES_CONN_ID,
    sql=f"DROP TABLE IF EXISTS {TABLE_NAME};",
    dag=dag,
)

create_table_task = PostgresOperator(
    task_id="create_postgres_table",
    postgres_conn_id=POSTGRES_CONN_ID,
    sql=f"""
        CREATE TABLE IF NOT EXISTS {TABLE_NAME} (
            id SERIAL PRIMARY KEY,
            lat DECIMAL(10, 6),
            lon DECIMAL(10, 6),
            data TIMESTAMP,
            satelite VARCHAR(30),
            pais VARCHAR(50),
            estado VARCHAR(50),
            municipio VARCHAR(100),
            bioma VARCHAR(50),
            geom GEOMETRY(Point, 4326),
            CONSTRAINT unique_lat_long_data_satelite UNIQUE (lat, lon, data)
        );
        
        CREATE INDEX IF NOT EXISTS idx_focos_calor_data_hora ON {TABLE_NAME}(data);
        CREATE INDEX IF NOT EXISTS idx_focos_calor_municipio ON {TABLE_NAME}(satelite);
        CREATE INDEX IF NOT EXISTS idx_focos_calor_geom ON {TABLE_NAME} USING GIST (geom);
    """,
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
    [
        create_dir_task >> download_extract_task,
        test_connection_postgres_task >> drop_table_task >> create_table_task,
    ]
    >> load_data_task
    >> cleanup_task
)

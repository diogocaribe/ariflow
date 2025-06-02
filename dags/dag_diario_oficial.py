from airflow import DAG
from airflow.providers.docker.operators.docker import DockerOperator
from datetime import datetime, timedelta
from airflow.operators.dummy import DummyOperator


default_args = {
    "owner": "airflow",
    "depends_on_past": False,  # Para não depender de execuções passadas
    "start_date": datetime(2022, 9, 9),
    "email_on_failure": False,
    "email_on_retry": False,
    "retries": 1,
}

dag = DAG(
    "diario_oficial",
    default_args=default_args,
    description="DAG to run diario_oficial in Docker",
    schedule_interval="@daily",  # Alterado de '@daily' para None
    catchup=True,  # Executar para datas passadas
    max_active_runs=3,  # Adicionado para controlar execuções simultâneas
    tags=["docker", "diario_oficial"],
)

start = DummyOperator(task_id="start", dag=dag)

run_raspar_doe = DockerOperator(
    task_id="coletando_doe_bruto",
    image="diario_oficial:latest",
    container_name="coleta_doe_bruto_{{ ts_nodash }}_{{ ds }}",
    docker_url="unix://var/run/docker.sock",
    network_mode="inema",
    auto_remove=True,
    command='raspar-doe-bruto {{ ds.split("-")|reverse|join("-") }}',  # Para formato DD-MM-YYYY
    dag=dag,
)

doe_bruto_publicacao = DockerOperator(
    task_id="transformando_doe_bruto_publicacao",
    image="diario_oficial:latest",
    container_name="doe_transformacao_{{ ts_nodash }}_{{ ds }}",
    docker_url="unix://var/run/docker.sock",
    network_mode="inema",
    auto_remove=True,
    command='transformar-doe-bruto-publicacao {{ ds.split("-")|reverse|join("-") }}',  # Para formato DD-MM-YYYY
    dag=dag,
)

transformar_publicacao_ato = DockerOperator(
    task_id="transformar_publicacao_ato",
    image="diario_oficial:latest",
    container_name="transformar_publicacao_ato_{{ ts_nodash }}_{{ ds }}",
    docker_url="unix://var/run/docker.sock",
    network_mode="inema",
    auto_remove=True,
    command='transformar-publicacao-ato',  # Para formato DD-MM-YYYY
    dag=dag,
)

finish = DummyOperator(task_id="finish", dag=dag)

start >> run_raspar_doe >> doe_bruto_publicacao >> transformar_publicacao_ato >> finish

from airflow import DAG
from airflow.providers.docker.operators.docker import DockerOperator
from datetime import datetime, timedelta

default_args = {
    'owner': 'airflow',
    'depends_on_past': False,
    'start_date': datetime(2021, 1, 1),
    'email_on_failure': False,
    'email_on_retry': False,
    'retries': 1,
    'retry_delay': timedelta(minutes=5),
}

dag = DAG(
    'my_python_app_dag',
    default_args=default_args,
    description='A simple DAG to run my-python-app in Docker',
    schedule_interval='@daily',
    catchup=False
)

run_app = DockerOperator(
    task_id='run_my_python_app',
    image='diario-oficial:latest',
    container_name='task_my_python_app',
    docker_url='unix://var/run/docker.sock',
    network_mode='bridge',
    auto_remove=True,
    mount_tmp_dir=False,
    dag=dag
)

run_app
from datetime import datetime, timedelta
from airflow import DAG
from airflow.providers.docker.operators.docker import DockerOperator
from airflow.operators.dummy import DummyOperator


default_args = {
    'owner': 'airflow',
    'depends_on_past': False,
    'start_date': datetime(2025, 1, 1),
    'email_on_failure': False,
    'email_on_retry': False,
    'retries': 1,
}

dag = DAG(
    'docker_hello_world',
    default_args=default_args,
    description='A simple DAG running Docker container',
    schedule_interval='@daily', #timedelta(seconds=10),
    catchup=True,
    tags=['example', 'docker']
)

start = DummyOperator(task_id='start', dag=dag)

docker_task = DockerOperator(
    task_id='docker_command',
    image='hello-world',  # Using official hello-world Docker image
    container_name='hello_world_{{ ts_nodash }}_{{ ds }}',
    api_version='auto',
    auto_remove=True,
    mount_tmp_dir=False,
    docker_url='unix://var/run/docker.sock',  # Connect to Docker daemon
    dag=dag
)

end = DummyOperator(task_id='end', dag=dag)

start >> docker_task >> end
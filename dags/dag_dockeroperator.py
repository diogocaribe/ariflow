from datetime import datetime, timedelta
from airflow import DAG
from airflow.providers.docker.operators.docker import DockerOperator
from airflow.operators.dummy import DummyOperator

default_args = {
    'owner': 'airflow',
    'depends_on_past': False,
    'start_date': datetime(2024, 12, 23),
    'email_on_failure': False,
    'email_on_retry': False,
    # 'retries': 1,
}

dag = DAG(
    'docker_hello_world',
    default_args=default_args,
    description='A simple DAG running Docker container',
    schedule_interval=timedelta(days=1),
)

start = DummyOperator(task_id='start', dag=dag)

docker_task = DockerOperator(
    task_id='docker_command',
    image='hello-world',  # Using official hello-world Docker image
    container_name='task_hello_world',
    api_version='auto',
    auto_remove=True,
    docker_url='unix://var/run/docker.sock',  # Connect to Docker daemon
    network_mode='bridge',
    mount_tmp_dir=False,
    dag=dag
)

end = DummyOperator(task_id='end', dag=dag)

start >> docker_task >> end
from os import access
from airflow import DAG
from airflow.providers.ssh.operators.ssh import SSHOperator
from airflow.operators.python_operator import PythonOperator
from airflow.models import Variable
from datetime import datetime, timedelta


def test_variable():
    password = Variable.get("SUDO_PASSWORD", default_var=None)
    print(f"Retrieved password: {password}")
    return password


default_args = {
    'owner': 'diogo.sousa',
    'start_date': datetime(2024, 1, 1),
    'retries': 1,
    'retry_delay': timedelta(minutes=5),
}

dag = DAG(
    'download_sentinel_metadata',
    default_args=default_args,
    schedule=None,
    catchup=False,
    tags=['pacatuba', 'harpia', 'download', 'metadata'],
)


test_login_variable = PythonOperator(
    task_id='test_login_variable',
    python_callable=test_variable,
    dag=dag
)


# Modified command to use echo and pipe to sudo -S
download_metadata = f'''echo "{test_variable()}" | sudo -S bash -c 'cd /opt/docker/service/harpia/ && ./run.sh --download-metadata' '''

run_download_metadata = SSHOperator(
    task_id='run_download_metadata',
    command=download_metadata,
    ssh_conn_id='pacatuba',
    cmd_timeout=600,
    conn_timeout=600,
    dag=dag)


test_login_variable >> run_download_metadata
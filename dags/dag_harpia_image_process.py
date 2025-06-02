from airflow import DAG
from airflow.providers.ssh.operators.ssh import SSHOperator
from airflow.operators.python_operator import PythonOperator
from airflow.models import Variable
from datetime import datetime, timedelta


def get_variable_password():
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
    'sentinel_img_process',
    default_args=default_args,
    schedule=None,
    catchup=False,
    tags=['pacatuba', 'harpia', 'sentinel', 'process'],
)


test_login_variable = PythonOperator(
    task_id='test_login_variable',
    python_callable=get_variable_password,
    dag=dag
)


# Modified command to use echo and pipe to sudo -S
sentinel_img_process = f'''echo "{get_variable_password()}" | sudo -S bash -c 'cd /opt/docker/service/harpia/ && ./run.sh --image-process' '''

run_sentinel_img_process = SSHOperator(
    task_id='run_sentinel_img_process',
    command=sentinel_img_process,
    ssh_conn_id='pacatuba',
    cmd_timeout=600,
    conn_timeout=600,
    dag=dag)


test_login_variable >> run_sentinel_img_process
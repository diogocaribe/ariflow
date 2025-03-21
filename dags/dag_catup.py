from airflow import DAG
from airflow.operators.python import PythonOperator
from datetime import datetime, timedelta

default_args = {
    'owner': 'airflow',
    'depends_on_past': False,
    'email_on_failure': False,
    'email_on_retry': False,
    'retries': 1,
    'retry_delay': timedelta(minutes=5)
}

def print_date(**context):
    execution_date = context['ds']
    print(f"Execution date is: {execution_date}")

with DAG(
    'print_dates_2025',
    default_args=default_args,
    description='DAG to print dates for 2025',
    schedule_interval='0 0 * * *',  # Run daily at midnight
    start_date=datetime(2025, 1, 1),
    end_date=datetime(2025, 12, 31),
    catchup=True,
    tags=['example']
) as dag:

    print_date_task = PythonOperator(
        task_id='print_date',
        python_callable=print_date,
        provide_context=True
    )
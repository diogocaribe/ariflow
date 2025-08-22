from datetime import datetime
from pathlib import Path
from airflow import DAG
from airflow.models import Variable
from airflow.operators.python import PythonVirtualenvOperator, PythonOperator


def get_variable_db_login():
    password = Variable.get("CERBERUS_PASSWORD", default_var=None)
    print(f"Retrieved password: {password}")
    return password

def manage_csv_files():
    """
    Manages CSV files by creating new ones and cleaning up old ones
    
    Args:
        base_dir: Base directory for files
        prefix: Prefix for new file name (usually date)
        file_pattern: Pattern to match old files for cleanup
    
    Returns:
        Path: Path object for the new file
    """
        
    # Clean up old files
    today = datetime.now().strftime("%Y%m%d")
    # Create base dir if it doesn't exist
    output_dir = Path('/opt/airflow/output/difis')

    # Check old files
    for file in output_dir.glob('*_difis_cerberus_tramitacao_processos.csv'):
        print(f"Checking file: {file}")
        file_date = file.name[:8]  # Extract date from filename (YYYYMMDD)
        if file_date != today:  # Keep only today's files
            try:
                if file.is_file():
                    print(f"Deleting old file: {file}")
                    file.unlink()  # Remove the file
            except FileNotFoundError:
                print(f"File not found: {file}")
            except Exception as e:
                print(f"Error deleting file {file}: {e}")
        else:
            print(f"Keeping file: {file}")

def execute_query_and_save():
    from airflow.models import Variable
    import pymssql
    import pandas as pd
    from datetime import datetime

    password = Variable.get("CERBERUS_PASSWORD", default_var=None)

    conn = pymssql.connect(host='172.16.0.14:1433\sql2012', 
                           user='adm.dados', 
                           password=password, 
                           charset='UTF-8', 
                           database='CERBERUS_2002', 
                           tds_version='7.0')
    cursor = conn.cursor()
    print("Connection successful")
    cursor.execute("""
        WITH area_destino AS (
            SELECT
                mp.processo_id,
                mp.area_usuario_destino_id,
                mp.usuario_destino_id,
                mp.data_hora,
                ROW_NUMBER() OVER (
                    PARTITION BY mp.processo_id, mp.area_usuario_destino_id
                    ORDER BY mp.data_hora
                ) AS rn
            FROM dbo.MOVIMENTO_PROCESSO mp
            WHERE mp.area_usuario_destino_id IN ('0199', '0054', '0200', '0025', '0279', '0198','0085','0278')
                AND mp.processo_id <> '' 
        ),
        filtered_area_destino AS (
            SELECT
                ad.processo_id,
                ad.area_usuario_destino_id,
                ad.usuario_destino_id,
                ad.data_hora,
                ad.rn
            FROM area_destino ad
            WHERE ad.rn = 1
        ),
        min_data AS (
            SELECT
                fad.processo_id,
                MIN(fad.data_hora) AS min_data_hora
            FROM filtered_area_destino fad
            GROUP BY fad.processo_id
        ),
        area_destino_saiu AS (
        SELECT
        mp.processo_id,
        mp.area_usuario_inicio_id,
        mp.data_hora,
        ROW_NUMBER() OVER (
        PARTITION BY mp.processo_id, mp.area_usuario_inicio_id
        ORDER BY mp.data_hora
        ) AS rn
        FROM movimento_processo mp
        WHERE mp.area_usuario_inicio_id IN ('0199', '0054', '0200', '0025', '0279', '0198','0085','0278') 
            AND mp.area_usuario_destino_id NOT IN ('0199', '0054', '0200', '0025', '0279', '0198','0085','0278')
        ),
        filtered_area_saiu AS (
        SELECT 
        ads.processo_id,
        ads.area_usuario_inicio_id,
        ads.data_hora,
        ads.rn
        FROM area_destino_saiu ads
        WHERE ads.rn = 1
        ), 
        min_data_saiu AS(
        SELECT 
        fas.processo_id,
        MIN(fas.data_hora) AS min_saiu_data_hora
        FROM filtered_area_saiu fas
        GROUP BY fas.processo_id
        ),
        ultimo_status AS (
            SELECT
                mp2.processo_id,
                p.numero,
                mp2.data_hora,
                st.status_processo,
                u2.nome AS [nome_realizador_inicio],
                mp2.area_usuario_inicio_id,
                a2.sigla AS [sigla_inicio],
                u.nome AS [nome_destino],
                a.sigla AS [sigla_destino],
                mp2.area_usuario_destino_id
            FROM MOVIMENTO_PROCESSO mp2
            LEFT JOIN usuario u ON u.usuario_id = mp2.usuario_destino_id
            LEFT JOIN usuario u2 ON u2.usuario_id = mp2.usuario_inicio_id 
            LEFT JOIN status_processo st ON mp2.status_processo_id = st.status_processo_id
            LEFT JOIN processo p ON p.processo_id = mp2.processo_id
            LEFT JOIN area a ON a.area_id = mp2.area_usuario_destino_id
            LEFT JOIN area a2 ON a2.area_id = mp2.area_usuario_inicio_id 
            WHERE mp2.fim_da_fila = 1 AND mp2.excluido <> 1
        ),
        ranked_processo_cliente AS (
        SELECT 
        processo_id,
        gerador_acao,
        cliente_id,
        COUNT(*) OVER (PARTITION BY processo_id) as registro_count,
        ROW_NUMBER() OVER (PARTITION BY processo_id ORDER BY gerador_acao) as rn
        FROM processo_cliente
        ),
        -- ? Rankea os movimentos em ordem decrescente
        status_ranked AS (
            SELECT
                mp.processo_id,
                mp.data_hora,
                st.status_processo,
                u2.nome AS responsavel,
                a2.sigla AS area_responsavel,
                ROW_NUMBER() OVER (
                    PARTITION BY mp.processo_id
                    ORDER BY mp.data_hora DESC
                ) AS rn
            FROM movimento_processo mp
            LEFT JOIN usuario u2 ON u2.usuario_id = mp.usuario_inicio_id
            LEFT JOIN area a2 ON a2.area_id = mp.area_usuario_inicio_id
            LEFT JOIN status_processo st ON mp.status_processo_id = st.status_processo_id
            WHERE mp.excluido <> 1
        ),
        -- ? Seleciona o último status válido, pulando áreas ATEND/Cerberus com base no INÍCIO
        status_anterior AS (
            SELECT s.processo_id,
                s.data_hora AS data_status_anterior,
                s.status_processo AS status_anterior,
                s.responsavel AS responsavel_anterior,
                s.area_responsavel AS area_responsavel_anterior
            FROM status_ranked s
            WHERE s.rn > 1
            AND s.area_responsavel NOT IN ('ATEND', 'Cerberus')
            AND NOT EXISTS (
                SELECT 1 FROM status_ranked s2
                WHERE s2.processo_id = s.processo_id
                    AND s2.rn > 1
                    AND s2.rn < s.rn
                    AND s2.area_responsavel NOT IN ('ATEND','Cerberus')
            )
        )
        SELECT
            fad.processo_id,
            p.numero AS [Número do Processo],
            fp.familia_processo AS [Família Processo],
            gtp.grupo_tipo_processo AS [Grupo do Processo],
            tp.tipo_processo AS [Tipo de Processo],
            p.descricao AS [Fato Gerador],
            p.data_formacao AS [Data de Formação],
            CASE
                WHEN p.municipio_id IS NULL THEN 'Sem registro no banco'
                WHEN m.municipio IS NULL THEN m2.municipio
                ELSE m.municipio
            END AS [Municipio no Processo],
            fad.data_hora AS [Data de Distribuição para Área],
            a.area AS [Área],
            a.sigla,
            u.nome AS [Responsável inicial na Área],
            ust.data_hora AS [Data do Status Atual],
            ust.nome_realizador_inicio AS [Realizador Status Atual],
            ust.sigla_inicio AS [Area Realizador Status Atual],
            ust.status_processo AS [Status Atual],
            ust.nome_destino AS [Responsável Atual],
            ust.sigla_destino AS [Área Responsável Atual],
            mds.min_saiu_data_hora AS [Data de Distribuição para fora da Área],
            m3.municipio AS [Municipio do Cliente],
            m3.uf_id AS [UF do Cliente],
            -- ? Novas colunas (agora usando usuario_inicio_id e area_usuario_inicio_id)
            sa.data_status_anterior AS [Data Status anterior à conclusão],
            sa.status_anterior AS [Status anterior à conclusão],
            sa.responsavel_anterior AS [Responsável anterior à conclusão],
            sa.area_responsavel_anterior AS [Área Responsável anterior à conclusão]
        FROM filtered_area_destino fad
        INNER JOIN min_data md ON fad.processo_id = md.processo_id AND fad.data_hora = md.min_data_hora
        LEFT JOIN min_data_saiu mds ON fad.processo_id = mds.processo_id
        LEFT JOIN processo p ON p.processo_id = fad.processo_id
        LEFT JOIN area a ON a.area_id = fad.area_usuario_destino_id
        LEFT JOIN usuario u ON u.usuario_id = fad.usuario_destino_id
        LEFT JOIN municipio_ba m ON p.municipio_id = m.municipio_id AND m.uf_id = 'BA'
        LEFT JOIN municipio m2 ON p.municipio_id = m2.municipio_id AND m2.uf_id = 'BA'
        LEFT JOIN ultimo_status ust ON ust.processo_id = fad.processo_id
        LEFT JOIN FAMILIA_PROCESSO fp ON fp.familia_processo_id = p.familia_processo_id
        LEFT JOIN GRUPO_TIPO_PROCESSO gtp ON gtp.grupo_tipo_processo_id = p.grupo_tipo_processo_id
        LEFT JOIN TIPO_PROCESSO tp ON tp.tipo_processo_id = p.tipo_processo_id
        LEFT JOIN (
        SELECT 
        *,
        CASE 
            WHEN rp.registro_count > 1 THEN '0'
            ELSE rp.gerador_acao
        END as gerador_acao_final
        FROM ranked_processo_cliente rp
        WHERE rn = 1
        ) rpc ON fad.processo_id = rpc.processo_id
        LEFT JOIN cliente c ON c.cliente_id = rpc.cliente_id
        LEFT JOIN cep ON cep.cep_id = c.cep_id
        LEFT JOIN municipio m3 ON cep.municipio_id = m3.municipio_id  AND m3.uf_id = cep.uf_id
        LEFT JOIN status_anterior sa ON sa.processo_id = fad.processo_id
        ORDER BY fad.processo_id ASC;
    """)

    # Get column names from cursor description
    columns = [column[0] for column in cursor.description]
    
    # Fetch all results
    results = cursor.fetchall()
    
    # Create DataFrame
    df = pd.DataFrame(results, columns=columns)
    print(df.head())
    
    # Optional: Save to CSV
    today = datetime.now().strftime("%Y%m%d_%H%M%S")
    file_name = f"{today}_difis_cerberus_tramitacao_processos.csv"
    df.to_csv(f'/opt/airflow/output/difis/{file_name}', index=False, sep=';')
    print(f"Data saved to {file_name}")
    # Close connections
    cursor.close()
    conn.close()
    print("Connection closed")


default_args = {
    'owner': 'diogo.sousa',
    'depends_on_past': False,
    'catchup': False,
    'start_date': datetime(2025, 4, 25),
    'retries': 3,
}

dag = DAG(
    'difis_cerberus_query_tramitacao_processos',
    default_args=default_args,
    description='DAG para executar consulta no banco de dados CERBERUS e retornar dados de tramitação de processos',
    tags=['difis', 'cerberus', 'csv'],
    schedule_interval='0 0 * * *'  # Executa todo dia à meia-noite (cron expression)
)

# Test the Variable 
get_variable_db_login = PythonOperator(
    task_id='get_variable_db_login',
    python_callable=get_variable_db_login,
    dag=dag
)

run_query_and_save = PythonVirtualenvOperator(
    task_id='difis_cerberus_query_tramitacao_processos',
    python_callable=execute_query_and_save,
    requirements=['pandas','pymssql==2.3.4'],
    system_site_packages=True, # <-- habilita acesso aos pacotes já instalados no sistema
    use_dill=True,
    dag=dag,
)

run_delete_csv_files = PythonOperator(
    task_id='delete_csv_files',
    python_callable=manage_csv_files)

get_variable_db_login >> run_query_and_save >> run_delete_csv_files
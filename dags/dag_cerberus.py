from datetime import datetime
from airflow import DAG
from airflow.operators.python import PythonVirtualenvOperator



def execute_query_and_save():
    import pymssql
    import pandas as pd
    from datetime import datetime

    conn = pymssql.connect(host='172.16.0.14:1433\sql2012', user='adm.dados', password='Inema2025', charset='UTF-8', database='CERBERUS_2002', tds_version='7.0')
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
            AND mp.processo_id <> '' -- Filtra processos com IDs vazios
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
    area_destino_saiu AS ( -- tabela com proessos tramitados para áreas foco e que possuem data de saída de quaisquer dos setores para outro fora da DIFIM
    SELECT
    mp.processo_id,
    mp.area_usuario_inicio_id,
    mp.data_hora,
    ROW_NUMBER() OVER (
    PARTITION BY mp.processo_id, mp.area_usuario_inicio_id
    ORDER BY mp.data_hora
    ) AS rn
    FROM movimento_processo mp
    WHERE mp.area_usuario_inicio_id IN ('0199', '0054', '0200', '0025', '0279', '0198','0085','0278') AND mp.area_usuario_destino_id not in ('0199', '0054', '0200', '0025', '0279', '0198','0085','0278')
    ),
    filtered_area_saiu AS ( -- filtra apenas o registro mais antigo de tramitação para fora das áreas foco DIFIS (data rn =1 de cada área)
    SELECT 
    ads.processo_id,
    ads.area_usuario_inicio_id,
    ads.data_hora,
    ads.rn
    FROM area_destino_saiu ads
    WHERE ads.rn = 1
    ), 
    min_data_saiu AS( -- filtra para retornar apenas a tramitação mais antiga para fora de quaisquer dos setores foco de interesse (apenas a primeira tramitação para fora da DIFIS)
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
            u.nome,
            mp2.area_usuario_destino_id,
            a.sigla
        FROM MOVIMENTO_PROCESSO mp2
        LEFT JOIN usuario u ON u.usuario_id = mp2.usuario_destino_id
        LEFT JOIN status_processo st ON mp2.status_processo_id = st.status_processo_id
        LEFT JOIN processo p ON p.processo_id = mp2.processo_id
        LEFT JOIN area a ON a.area_id = mp2.area_usuario_destino_id
        WHERE mp2.fim_da_fila = 1 AND mp2.excluido <> 1
    ),
    ranked_processo_cliente AS ( -- busca informação atualizada da relação dos dados do cliente com o processo (tabela processo_cliente), para buscar o municipio do cliente de forma correta
    SELECT 
    processo_id,
    gerador_acao,
    cliente_id,
    COUNT(*) OVER (PARTITION BY processo_id) as registro_count,
    ROW_NUMBER() OVER (PARTITION BY processo_id ORDER BY gerador_acao) as rn
    FROM 
    processo_cliente
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
        ust.status_processo AS [Status Atual],
        ust.nome AS [Responsável Atual],
        ust.sigla AS [Área Responsável Atual],
        mds.min_saiu_data_hora AS [Data de Distribuição para fora da Área],
        m3.municipio AS [Municipio do Cliente],
        m3.uf_id AS [UF do Cliente]
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
    df.to_csv(f'/opt/airflow/output/difis/{file_name}', index=False)
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

hello_task = PythonVirtualenvOperator(
    task_id='difis_cerberus_query_tramitacao_processos',
    python_callable=execute_query_and_save,
    requirements=['pandas','pymssql'],
    system_site_packages=True, # <-- habilita acesso aos pacotes já instalados no sistema
    dag=dag,
)

hello_task
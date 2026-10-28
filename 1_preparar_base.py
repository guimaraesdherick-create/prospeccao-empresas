"""
Passo 1 - Prepara a base de prospecção.

Como usar:
  1. Baixe os arquivos .zip dos Dados Abertos do CNPJ (Receita Federal):
     Empresas*, Estabelecimentos*, Cnaes, Municipios
  2. Extraia TODOS os zips dentro da pasta "dados" (ao lado deste script).
  3. Rode:  python 1_preparar_base.py

Gera o arquivo prospeccao.duckdb, usado pelo app (2_app.py).
Só ficam na base os estabelecimentos com situação cadastral ATIVA.
"""
import glob
import os
import sys

import duckdb

PASTA = "dados"
SAIDA = "prospeccao.duckdb"


def achar(padrao):
    arquivos = [
        f for f in glob.glob(os.path.join(PASTA, "**", "*"), recursive=True)
        if os.path.isfile(f) and padrao in os.path.basename(f).upper()
    ]
    if not arquivos:
        sys.exit(f"Não encontrei arquivos com '{padrao}' na pasta '{PASTA}'. "
                 "Confira se extraiu os .zip lá dentro.")
    return sorted(arquivos)


estab_files = achar("ESTABELE")
emp_files = achar("EMPRECSV")
cnae_files = achar("CNAECSV")
mun_files = achar("MUNICCSV")

print(f"Estabelecimentos: {len(estab_files)} arquivo(s)")
print(f"Empresas: {len(emp_files)} arquivo(s)")

COLS_ESTAB = [
    "cnpj_basico", "cnpj_ordem", "cnpj_dv", "matriz_filial", "nome_fantasia",
    "situacao", "data_situacao", "motivo", "cidade_exterior", "pais",
    "data_inicio", "cnae_principal", "cnae_secundaria", "tipo_logradouro",
    "logradouro", "numero", "complemento", "bairro", "cep", "uf", "municipio",
    "ddd1", "tel1", "ddd2", "tel2", "ddd_fax", "fax", "email",
    "situacao_especial", "data_situacao_especial",
]
COLS_EMP = [
    "cnpj_basico", "razao_social", "natureza_juridica",
    "qualificacao_responsavel", "capital_social", "porte", "ente_federativo",
]


def lit(lista):
    """Converte lista Python em literal de lista SQL."""
    return "[" + ", ".join("'" + str(x).replace("'", "''") + "'" for x in lista) + "]"


def csv(arquivos, colunas):
    return (f"read_csv({lit(arquivos)}, delim=';', header=false, quote='\"', "
            f"encoding='utf-8', all_varchar=true, ignore_errors=true, "
            f"names={lit(colunas)})")


con = duckdb.connect(SAIDA)

print("Lendo estabelecimentos ativos (pode levar alguns minutos)...")
con.execute("DROP TABLE IF EXISTS estab")
con.execute(f"CREATE TABLE estab AS SELECT * FROM {csv(estab_files, COLS_ESTAB)} WHERE situacao = '02'")

print("Lendo empresas...")
con.execute("DROP TABLE IF EXISTS emp")
con.execute(f"CREATE TABLE emp AS SELECT * FROM {csv(emp_files, COLS_EMP)}")

print("Lendo CNAEs e municípios...")
con.execute("DROP TABLE IF EXISTS cnaes")
con.execute(f"CREATE TABLE cnaes AS SELECT * FROM {csv(cnae_files, ['codigo', 'descricao'])}")
con.execute("DROP TABLE IF EXISTS municipios")
con.execute(f"CREATE TABLE municipios AS SELECT * FROM {csv(mun_files, ['codigo', 'descricao'])}")

print("Montando tabela final...")
con.execute("DROP TABLE IF EXISTS base")
con.execute(
    """
CREATE TABLE base AS
SELECT
  concat(e.cnpj_basico, e.cnpj_ordem, e.cnpj_dv)              AS cnpj,
  emp.razao_social                                             AS razao_social,
  nullif(trim(e.nome_fantasia), '')                            AS nome_fantasia,
  CASE emp.porte WHEN '01' THEN 'Microempresa'
                 WHEN '03' THEN 'Empresa de pequeno porte'
                 WHEN '05' THEN 'Demais'
                 ELSE 'Não informado' END                      AS porte,
  try_cast(replace(emp.capital_social, ',', '.') AS DOUBLE)    AS capital_social,
  e.cnae_principal                                             AS cnae_principal,
  c.descricao                                                  AS cnae_descricao,
  nullif(trim(e.cnae_secundaria), '')                          AS cnae_secundaria,
  e.uf                                                         AS uf,
  m.descricao                                                  AS municipio,
  nullif(trim(e.bairro), '')                                   AS bairro,
  nullif(trim(e.cep), '')                                      AS cep,
  trim(concat_ws(' ', e.tipo_logradouro, e.logradouro, ',',
                 e.numero, e.complemento))                     AS endereco,
  nullif(concat_ws('', e.ddd1, e.tel1), '')                    AS telefone,
  nullif(concat_ws('', e.ddd2, e.tel2), '')                    AS telefone2,
  nullif(lower(trim(e.email)), '')                             AS email,
  try_strptime(e.data_inicio, '%Y%m%d')::DATE                  AS data_inicio,
  e.matriz_filial = '1'                                        AS eh_matriz
FROM estab e
LEFT JOIN emp          ON emp.cnpj_basico = e.cnpj_basico
LEFT JOIN cnaes c      ON c.codigo = e.cnae_principal
LEFT JOIN municipios m ON m.codigo = e.municipio
"""
)

n = con.execute("SELECT count(*) FROM base").fetchone()[0]
print(f"Pronto! {n:,} estabelecimentos ativos gravados em {SAIDA}")
con.close()

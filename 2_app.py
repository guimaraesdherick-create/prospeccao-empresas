"""
Passo 2 - App de prospecção com filtros.

Rode:  streamlit run 2_app.py
"""
import io
import re

import duckdb
import pandas as pd
import streamlit as st

DB = "prospeccao.duckdb"

st.set_page_config(page_title="Prospecção de empresas", layout="wide")
st.title("🔎 Prospecção de empresas por CNAE e região")


@st.cache_resource
def conectar():
    return duckdb.connect(DB, read_only=True)


@st.cache_data
def listar_ufs():
    return [r[0] for r in conectar().execute(
        "SELECT DISTINCT uf FROM base WHERE uf IS NOT NULL ORDER BY uf").fetchall()]


@st.cache_data
def listar_municipios(ufs):
    if not ufs:
        return []
    return [r[0] for r in conectar().execute(
        "SELECT DISTINCT municipio FROM base WHERE uf IN (SELECT unnest(?::VARCHAR[])) "
        "AND municipio IS NOT NULL ORDER BY municipio", [list(ufs)]).fetchall()]


@st.cache_data
def listar_cnaes():
    rows = conectar().execute(
        "SELECT cnae_principal, any_value(cnae_descricao), count(*) "
        "FROM base WHERE cnae_principal IS NOT NULL "
        "GROUP BY 1 ORDER BY 1").fetchall()
    return rows


def fmt_cnae(c):
    return f"{c[:4]}-{c[4]}/{c[5:]}" if c and len(c) == 7 else c


def so_digitos(txt):
    return re.sub(r"\D", "", txt)


# ---------------------------------------------------------------- filtros
try:
    ufs_disp = listar_ufs()
except Exception as e:  # base não existe
    st.error("Não consegui abrir a base. Rode primeiro: python 1_preparar_base.py")
    st.stop()

cnaes = listar_cnaes()
opcoes_cnae = {f"{fmt_cnae(c)} — {d} ({n:,})": c for c, d, n in cnaes}

with st.sidebar:
    st.header("Filtros")

    st.subheader("📍 Região")
    ufs = st.multiselect("Estado (UF)", ufs_disp, default=["SC"] if "SC" in ufs_disp else [])
    municipios = st.multiselect(
        "Município (vazio = todos do estado)", listar_municipios(tuple(ufs)))
    bairro_txt = st.text_input("Bairro contém (opcional)")

    st.subheader("🏷️ CNAE")
    escolhidos = st.multiselect(
        "Atividades (digite código ou palavra, ex.: 'estética automotiva')",
        list(opcoes_cnae.keys()))
    colados = st.text_area(
        "Ou cole códigos CNAE (separados por vírgula/linha)",
        placeholder="4520-0/01, 4520-0/05, 9602501")
    incluir_sec = st.checkbox("Incluir empresas com esse CNAE como secundário", value=False)

    st.subheader("🏢 Perfil")
    portes = st.multiselect(
        "Porte", ["Microempresa", "Empresa de pequeno porte", "Demais", "Não informado"])
    idade_min = st.slider("Empresa aberta há pelo menos (anos)", 0, 30, 0)
    so_matriz = st.checkbox("Somente matriz", value=True)

    st.subheader("📞 Contato")
    exige_email = st.checkbox("Só com e-mail")
    exige_tel = st.checkbox("Só com telefone")
    ocultar_contab = st.checkbox(
        "Ocultar e-mails que parecem de contabilidade", value=True,
        help="Na base da Receita o e-mail costuma ser do contador, não da empresa.")

# ---------------------------------------------------------------- consulta
codigos = {opcoes_cnae[k] for k in escolhidos}
for tok in re.split(r"[,\n;]+", colados):
    d = so_digitos(tok)
    if len(d) == 7:
        codigos.add(d)

where, params = [], []

if ufs:
    where.append("uf IN (SELECT unnest(?::VARCHAR[]))")
    params.append(list(ufs))
if municipios:
    where.append("municipio IN (SELECT unnest(?::VARCHAR[]))")
    params.append(list(municipios))
if bairro_txt.strip():
    where.append("bairro ILIKE ?")
    params.append(f"%{bairro_txt.strip()}%")

if codigos:
    lista = sorted(codigos)
    cond = "cnae_principal IN (SELECT unnest(?::VARCHAR[]))"
    params.append(lista)
    if incluir_sec:
        cond += (" OR list_has_any(string_split(coalesce(cnae_secundaria,''), ','), ?::VARCHAR[])")
        params.append(lista)
    where.append(f"({cond})")

if portes:
    where.append("porte IN (SELECT unnest(?::VARCHAR[]))")
    params.append(portes)
if idade_min:
    where.append("data_inicio <= current_date - to_years(?::INTEGER)")
    params.append(idade_min)
if so_matriz:
    where.append("eh_matriz")
if exige_email:
    where.append("email IS NOT NULL")
if exige_tel:
    where.append("telefone IS NOT NULL")
if ocultar_contab:
    where.append("(email IS NULL OR email NOT ILIKE '%contab%' "
                 "AND email NOT ILIKE '%contador%' AND email NOT ILIKE '%assessoria%')")

sql_where = ("WHERE " + " AND ".join(where)) if where else ""
con = conectar()

if not codigos and not ufs:
    st.info("Escolha ao menos um estado ou um CNAE na barra lateral para começar.")
    st.stop()

total = con.execute(f"SELECT count(*) FROM base {sql_where}", params).fetchone()[0]
c1, c2, c3 = st.columns(3)
c1.metric("Empresas encontradas", f"{total:,}")
c2.metric("CNAEs selecionados", len(codigos) or "todos")
c3.metric("Municípios", len(municipios) or ("todos" if ufs else "-"))

if total == 0:
    st.warning("Nenhuma empresa com esses filtros.")
    st.stop()

LIMITE_EXPORT = 200_000
df = con.execute(
    f"SELECT * FROM base {sql_where} ORDER BY municipio, razao_social LIMIT {LIMITE_EXPORT}",
    params).fetchdf()

df["cnae_principal"] = df["cnae_principal"].map(fmt_cnae)


def link_whatsapp(tel):
    if not isinstance(tel, str) or len(tel) < 10:
        return None
    numero = tel[2:]
    if len(numero) == 9 and numero.startswith("9"):  # celular
        return f"https://wa.me/55{tel}"
    return None


df["whatsapp"] = df["telefone"].map(link_whatsapp)
df = df.drop(columns=["eh_matriz"])

st.dataframe(df.head(1000), use_container_width=True, height=520,
             column_config={"whatsapp": st.column_config.LinkColumn("whatsapp")})
if total > 1000:
    st.caption(f"Mostrando as 1.000 primeiras linhas; a planilha exportada traz "
               f"até {LIMITE_EXPORT:,}.")

# ---------------------------------------------------------------- exportar
buf = io.BytesIO()
with pd.ExcelWriter(buf, engine="openpyxl") as w:
    df.to_excel(w, index=False, sheet_name="Prospects")
    ws = w.sheets["Prospects"]
    ws.freeze_panes = "A2"
    for col in ws.columns:
        tamanho = max(len(str(c.value)) if c.value is not None else 0 for c in col[:200])
        ws.column_dimensions[col[0].column_letter].width = min(max(tamanho + 2, 10), 50)

b1, b2, _ = st.columns([1, 1, 4])
b1.download_button("⬇️ Baixar Excel", buf.getvalue(), "prospects.xlsx",
                   "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
b2.download_button("⬇️ Baixar CSV", df.to_csv(index=False, sep=";").encode("utf-8-sig"),
                   "prospects.csv", "text/csv")

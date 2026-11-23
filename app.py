import os
import io
import json
import streamlit as st
from dotenv import load_dotenv
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload
from azure.storage.blob import BlobServiceClient

load_dotenv()

st.set_page_config(page_title="Migração Drive → Azure", page_icon="", layout="wide")

# Função auxiliar para ler variáveis tanto localmente (.env) quanto na nuvem (st.secrets)
def get_config(chave):
    try:
        if chave in st.secrets:
            return st.secrets[chave]
    except Exception:
        pass
    return os.getenv(chave)

FOLDER_ID = get_config("GOOGLE_FOLDER_ID")
AZURE_CONN_STRING = get_config("AZURE_CONNECTION_STRING")
CONTAINER_NAME = get_config("AZURE_CONTAINER_NAME")

# 1. Autenticação segura no Google Drive
def autenticar_drive():
    scopes = ['https://www.googleapis.com/auth/drive.readonly']
    cred_json = get_config("GOOGLE_CREDENTIALS_JSON")
    if cred_json:
        info = json.loads(cred_json)
        creds = service_account.Credentials.from_service_account_info(info, scopes=scopes)
    else:
        creds = service_account.Credentials.from_service_account_file("credentials.json", scopes=scopes)
    return build('drive', 'v3', credentials=creds)

# 2. Autenticação segura no Azure Blob Storage
def autenticar_azure():
    blob_service = BlobServiceClient.from_connection_string(AZURE_CONN_STRING)
    container_client = blob_service.get_container_client(CONTAINER_NAME)
    if not container_client.exists():
        container_client.create_container()
    return container_client

# 3. Requisito: Função para listar dados de origem (Google Drive)
def listar_origem(drive_service):
    results = drive_service.files().list(
        q=f"'{FOLDER_ID}' in parents and trashed = false",
        fields="files(id, name, mimeType, size)"
    ).execute()
    return results.get('files', [])

# 4. Requisito: Função para listar dados de destino (Azure Blob Storage)
def listar_destino(container_client):
    return list(container_client.list_blobs())

# --- INTERFACE GRÁFICA ---
st.title("Migração de Arquivos: Google Drive → Azure Blob Storage")
st.caption(f"Contêiner de destino: **{CONTAINER_NAME}**")

try:
    drive = autenticar_drive()
    container = autenticar_azure()
except Exception as e:
    st.error(f"Erro de autenticação: {e}")
    st.stop()

col1, col2 = st.columns(2)

with col1:
    st.subheader("Origem (Google Drive)")
    arquivos_origem = listar_origem(drive)
    if not arquivos_origem:
        st.info("Nenhum arquivo na pasta de origem.")
    else:
        for arq in arquivos_origem:
            st.write(f"**{arq['name']}** ({arq.get('size', '?')} bytes)")

with col2:
    st.subheader("Destino (Azure Blob Storage)")
    blobs_destino = listar_destino(container)
    if not blobs_destino:
        st.info("Contêiner vazio no Azure.")
    else:
        for blob in blobs_destino:
            st.write(f"**{blob.name}** ({blob.size} bytes)")

st.divider()

if st.button("Iniciar Migração de Arquivos", type="primary"):
    if not arquivos_origem:
        st.warning("Não há arquivos na pasta do Google Drive para transferir.")
    else:
        st.subheader("Log de Transferências")
        for arq in arquivos_origem:
            nome = arq['name']
            try:
                if "application/vnd.google-apps" in arq['mimeType']:
                    st.warning(f"[AVISO] Arquivo nativo Google ignorado: {nome}")
                    continue

                # Download do Google Drive para memória
                request = drive.files().get_media(fileId=arq['id'])
                fh = io.BytesIO()
                downloader = MediaIoBaseDownload(fh, request)
                done = False
                while not done:
                    _, done = downloader.next_chunk()
                fh.seek(0)

                # Upload para o Azure Blob Storage
                blob_client = container.get_blob_client(nome)
                blob_client.upload_blob(fh, overwrite=True)

                print(f"[SUCESSO] {nome} transferido.")
                st.success(f"[SUCESSO] Arquivo **{nome}** transferido com êxito!")
            except Exception as err:
                print(f"[ERRO] {nome}: {err}")
                st.error(f"[ERRO] Falha ao transferir **{nome}**: {err}")

        st.button("Atualizar Listas")
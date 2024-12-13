#!/usr/bin/env python
# coding: utf-8

# ### Importação das Bibliotecas

# In[ ]:


import streamlit as st
import pytz
import openai
import datetime
import sqlite3
from contextlib import contextmanager
import os
from openai import OpenAI
from openai import OpenAIError
from datetime import datetime, time, timedelta
import logging
from dotenv import load_dotenv, find_dotenv
import os.path
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from google.oauth2 import service_account
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError







# ### Implementação dos Modelos do Banco de Dados

# In[3]:


# Função para converter as linhas do banco de dados em dicionários
def dict_factory(cursor, row):
    d = {}
    for idx, col in enumerate(cursor.description):
        d[col[0]] = row[idx]
    return d

# Função para conectar ao banco de dados com contexto gerenciado
@contextmanager
def get_db_connection():
    conn = sqlite3.connect('database.db')
    conn.row_factory = dict_factory
    try:
        yield conn
    finally:
        conn.close()

# Função para criar as tabelas necessárias
def create_tables():
    create_tables_sql = """
    CREATE TABLE IF NOT EXISTS pacientes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        nome TEXT NOT NULL,
        data_nascimento DATE NOT NULL,
        contato TEXT NOT NULL,
        endereco TEXT NOT NULL,
        historico_medico TEXT NOT NULL,
        historico_familiar TEXT NOT NULL,
        alergias TEXT,
        medicacoes_atuais TEXT,
        data_cadastro DATE NOT NULL
    );

    CREATE TABLE IF NOT EXISTS sessoes_terapia (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        paciente_id INTEGER NOT NULL,
        data_sessao DATE NOT NULL,
        notas TEXT NOT NULL,
        FOREIGN KEY (paciente_id) REFERENCES pacientes (id)
    );

    CREATE TABLE IF NOT EXISTS prontuarios (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        paciente_id INTEGER NOT NULL,
        conteudo TEXT NOT NULL,
        FOREIGN KEY (paciente_id) REFERENCES pacientes (id)
    );

    CREATE TABLE IF NOT EXISTS mensagens (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        remetente_id INTEGER NOT NULL,
        destinatario_id INTEGER NOT NULL,
        conteudo TEXT NOT NULL,
        data_envio DATETIME NOT NULL,
        FOREIGN KEY (remetente_id) REFERENCES pacientes (id),
        FOREIGN KEY (destinatario_id) REFERENCES pacientes (id)
    );
    """

    # Uso do contexto with para garantir que a conexão seja fechada automaticamente
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.executescript(create_tables_sql)
        conn.commit()

# Chamar a função para criar as tabelas
create_tables()


# ### Definição de Classes

# #### Classe Paciente

# In[5]:


class Paciente:
    def __init__(self, nome, data_nascimento, contato, endereco, historico_medico, historico_familiar, alergias, medicacoes_atuais):
        self.nome = nome
        self.data_nascimento = data_nascimento
        self.contato = contato
        self.endereco = endereco
        self.historico_medico = historico_medico
        self.historico_familiar = historico_familiar
        self.alergias = alergias
        self.medicacoes_atuais = medicacoes_atuais

    def cadastrar(self):
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO pacientes (nome, data_nascimento, contato, endereco, historico_medico, historico_familiar, alergias, medicacoes_atuais)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (self.nome, self.data_nascimento, self.contato, self.endereco, self.historico_medico, self.historico_familiar, self.alergias, self.medicacoes_atuais)
            )
            conn.commit()


# #### Classe SessaoTerapia

# In[6]:


class SessaoTerapia:
    def __init__(self, paciente_id, data_sessao, notas):
        self.paciente_id = paciente_id
        self.data_sessao = data_sessao
        self.notas = notas

    def registrar(self):
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO sessoes_terapia (paciente_id, data_sessao, notas)
                VALUES (?, ?, ?)
                """,
                (self.paciente_id, self.data_sessao, self.notas)
            )
            conn.commit()


# #### Classe Prontuário

# In[7]:


class Prontuario:
    def __init__(self, paciente_id, conteudo):
        self.paciente_id = paciente_id
        self.conteudo = conteudo

    def criar_atualizar(self):
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO prontuarios (paciente_id, conteudo)
                VALUES (?, ?)
                ON CONFLICT(paciente_id) DO UPDATE SET conteudo=excluded.conteudo
                """,
                (self.paciente_id, self.conteudo)
            )
            conn.commit()

    @staticmethod
    def buscar(palavra_chave):
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM prontuarios WHERE conteudo LIKE ?", ('%' + palavra_chave + '%',))
            prontuarios = cursor.fetchall()
        return prontuarios


# #### Classe Calendário

# In[ ]:


class Calendario:
    SERVICE_ACCOUNT_FILE = 'path/to/credentials.json'
    SCOPES = ['https://www.googleapis.com/auth/calendar']

    @staticmethod
    def get_calendar_service():
        creds = None
        if os.path.exists('token.json'):
            try:
                creds = Credentials.from_authorized_user_file('token.json', Calendario.SCOPES)
            except Exception as e:
                st.error(f"Erro ao carregar token.json: {e}. Regenerando token...")
                os.remove('token.json')

        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                flow = InstalledAppFlow.from_client_secrets_file(
                    'credentials.json',
                    Calendario.SCOPES
                )
                flow.redirect_uri = 'http://localhost:65015/'  # Atualize para o URI correto
                creds = flow.run_local_server(
                    port=0,
                    authorization_prompt_message="Por favor, autentique usando a nova conta Google."
                )

            # Salve o token gerado para uso futuro
            with open('token.json', 'w') as token:
                token.write(creds.to_json())

        return build('calendar', 'v3', credentials=creds)



    @staticmethod
    def create_event(summary, start_time, end_time):
        service = Calendario.get_calendar_service()
        event = {
            'summary': summary,
            'start': {'dateTime': start_time, 'timeZone': 'America/Manaus'},
            'end': {'dateTime': end_time, 'timeZone': 'America/Manaus'},
            'conferenceData': {
                'createRequest': {
                    'conferenceSolutionKey': {'type': 'hangoutsMeet'},
                    'requestId': 'some-random-string'
                }
            }
        }
        created_event = service.events().insert(calendarId='primary', body=event, conferenceDataVersion=1).execute()
        return created_event['hangoutLink']

    @staticmethod
    def get_events(start_date, end_date):
        service = Calendario.get_calendar_service()
        events_result = service.events().list(
            calendarId='primary', timeMin=start_date, timeMax=end_date, 
            singleEvents=True, orderBy='startTime').execute()
        return events_result.get('items', [])


# ### Implementação do Cadastro de Pacientes

# In[3]:


def cadastrar_paciente(nome, data_nascimento, contato, endereco, historico_medico, historico_familiar, alergias, medicacoes_atuais):
    data_cadastro = datetime.today().strftime('%Y-%m-%d')  # Captura a data de hoje para o cadastro
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO pacientes (nome, data_nascimento, contato, endereco, historico_medico, historico_familiar, alergias, medicacoes_atuais, data_cadastro)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (nome, data_nascimento, contato, endereco, historico_medico, historico_familiar, alergias, medicacoes_atuais, data_cadastro)
        )
        conn.commit()

def pagina_cadastro_pacientes():
    # Defina os limites de data dentro da função
    min_date = datetime(1900, 1, 1)
    max_date = datetime.now()
    st.title("Cadastro de Pacientes")

    nome = st.text_input("Nome")
    # Adicione o campo de data de nascimento com os limites ajustados
    data_nascimento = st.date_input(
        "Data de Nascimento",
        value=datetime.now(),  # Data padrão
        min_value=min_date,
        max_value=max_date
    )
    # Formate a data no formato dd/mm/aaaa
    #data_nascimento_formatada = data_nascimento.strftime('%d/%m/%Y')
    contato = st.text_input("Contato")
    endereco = st.text_area("Endereço")
    historico_medico = st.text_area("Histórico Médico")
    historico_familiar = st.text_area("Histórico Familiar")
    alergias = st.text_area("Alergias", "")
    medicacoes_atuais = st.text_area("Medicações Atuais", "")

    if st.button("Cadastrar"):
        cadastrar_paciente(nome, data_nascimento, contato, endereco, historico_medico, historico_familiar, alergias, medicacoes_atuais)
        st.success("Paciente cadastrado com sucesso!")


# ### Integração com Google Calendar API

# In[2]:


class Calendario:
    SCOPES = ['https://www.googleapis.com/auth/calendar']

    @staticmethod
    def get_calendar_service():
        creds = None
        if os.path.exists('token.json'):
            creds = Credentials.from_authorized_user_file('token.json', Calendario.SCOPES)
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                flow = InstalledAppFlow.from_client_secrets_file(
                    'credentials.json', Calendario.SCOPES)
                creds = flow.run_local_server(port=0)
            with open('token.json', 'w') as token:
                token.write(creds.to_json())

        service = build('calendar', 'v3', credentials=creds)
        return service

    @staticmethod
    def create_event(summary, start_time):
        service = Calendario.get_calendar_service()
        # Definir duração padrão de 1 hora
        start_datetime = datetime.fromisoformat(start_time)
        end_datetime = start_datetime + timedelta(hours=1)
        event = {
            'summary': summary,
            'start': {'dateTime': start_time},
            'end': {'dateTime': end_datetime.isoformat()},
        }
        try:
            event = service.events().insert(calendarId='primary', body=event).execute()
            return event
        except HttpError as error:
            raise error

    @staticmethod
    def update_event(event_id, summary, start_time):
        service = Calendario.get_calendar_service()
        try:
            event = service.events().get(calendarId='primary', eventId=event_id).execute()

            event['summary'] = summary
            event['start']['dateTime'] = start_time

            # Atualizar horário de término com base na duração padrão
            start_datetime = datetime.fromisoformat(start_time)
            end_datetime = start_datetime + timedelta(hours=1)
            event['end']['dateTime'] = end_datetime.isoformat()

            updated_event = service.events().update(calendarId='primary', eventId=event_id, body=event).execute()
            return updated_event
        except HttpError as error:
            raise error

    @staticmethod
    def get_events(start_date, end_date):
        service = Calendario.get_calendar_service()
        try:
            events_result = service.events().list(
                calendarId='primary', timeMin=start_date, timeMax=end_date,
                singleEvents=True, orderBy='startTime').execute()
            return events_result.get('items', [])
        except HttpError as error:
            raise error

    @staticmethod
    def delete_event(event_id):
        service = Calendario.get_calendar_service()
        try:
            service.events().delete(calendarId='primary', eventId=event_id).execute()
        except HttpError as error:
            raise error


# ### Agendamento de Consulta/Terapia

# In[ ]:


def pagina_agendar_consulta():
    st.title("Agendar Consulta")
    st.markdown(':red[**Agendar neste campo somente se o paciente fez contato direto**]')

    # Formulário para criar um novo evento
    st.header("Criar Novo Evento")
    evento_resumo = st.text_input("Resumo do Evento", key='create_resumo')
    data_inicio = st.date_input("Data de Início", key='create_data_inicio', format="DD.MM.YYYY")
    hora_inicio = st.time_input("Hora de Início", key='create_hora_inicio')

    timezone_bv = pytz.timezone('America/Manaus')

    if st.button("Criar Evento"):
        start_datetime = timezone_bv.localize(datetime.combine(data_inicio, hora_inicio))

        try:
            Calendario.create_event(evento_resumo, start_datetime.isoformat())
            st.success("Evento criado com sucesso no Google Calendar!")
        except HttpError as error:
            st.error(f"Ocorreu um erro ao criar o evento: {error}")
        st.experimental_rerun()

    # Mostrar o calendário com eventos
    st.header("Visualizar e Gerenciar Consultas Agendadas")
    calendario_data = st.date_input("Selecione um dia para visualizar as consultas",
                                    key='view_data',
                                    format="DD.MM.YYYY")

    if calendario_data:
        start_date = timezone_bv.localize(datetime.combine(calendario_data, time.min)).isoformat()
        end_date = timezone_bv.localize(datetime.combine(calendario_data, time.max)).isoformat()

        try:
            eventos = Calendario.get_events(start_date, end_date)
        except HttpError as error:
            st.error(f"Ocorreu um erro ao recuperar os eventos: {error}")
            return

        if eventos:
            # Exibir eventos em formato de lista
            st.subheader(f"Eventos em {calendario_data.strftime('%d.%m.%Y')}:")
            for evento in eventos:
                resumo = evento.get('summary', 'Sem Título')
                inicio_str = evento['start'].get('dateTime', evento['start'].get('date'))

                # Converter string para datetime
                inicio_datetime = datetime.fromisoformat(inicio_str.replace('Z', '+00:00'))
                inicio_formatado = inicio_datetime.strftime('%d.%m.%Y %H:%M')

                st.write(f"- **{resumo}**: {inicio_formatado}")

            # Selecionar um evento para editar ou excluir
            evento_selecionado = st.selectbox(
                "Selecione um evento para editar ou excluir",
                options=eventos,
                format_func=lambda x: f"{x.get('summary', 'Sem Título')} ({datetime.fromisoformat(x['start'].get('dateTime', x['start'].get('date')).replace('Z', '+00:00')).strftime('%d.%m.%Y %H:%M')})"
            )

            if evento_selecionado:
                st.subheader("Editar Evento Selecionado")
                evento_id = evento_selecionado['id']
                evento_resumo_edit = st.text_input("Resumo do Evento", value=evento_selecionado.get('summary', ''), key='edit_resumo')
                inicio_str = evento_selecionado['start'].get('dateTime', evento_selecionado['start'].get('date'))

                # Converter string para datetime
                inicio_datetime = datetime.fromisoformat(inicio_str.replace('Z', '+00:00'))

                data_inicio_edit = st.date_input("Data de Início", value=inicio_datetime.date(), key='edit_data_inicio')
                hora_inicio_edit = st.time_input("Hora de Início", value=inicio_datetime.time(), key='edit_hora_inicio')

                if st.button("Atualizar Evento"):
                    start_datetime = timezone_bv.localize(datetime.combine(data_inicio_edit, hora_inicio_edit))

                    try:
                        Calendario.update_event(evento_id, evento_resumo_edit, start_datetime.isoformat())
                        st.success("Evento atualizado com sucesso no Google Calendar!")
                    except HttpError as error:
                        st.error(f"Ocorreu um erro ao atualizar o evento: {error}")
                    st.experimental_rerun()

                if st.button("Excluir Evento"):
                    try:
                        Calendario.delete_event(evento_id)
                        st.success("Evento excluído com sucesso do Google Calendar!")
                    except HttpError as error:
                        st.error(f"Ocorreu um erro ao excluir o evento: {error}")
                    st.experimental_rerun()
        else:
            st.write("Não há eventos agendados para esta data.")



# ### Implementação do Registro de Sessões de Terapia

# In[13]:


def registrar_sessao_terapia(paciente_id, data_sessao, notas):
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO sessoes_terapia (paciente_id, data_sessao, notas)
            VALUES (?, ?, ?)
            """,
            (paciente_id, data_sessao, notas)
        )
        conn.commit()

def pagina_registro_sessoes():
    st.title("Registro de Sessões de Terapia")

    # Selecionar paciente
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id, nome FROM pacientes")
        pacientes = cursor.fetchall()

    paciente_selecionado = st.selectbox("Selecione o Paciente", pacientes, format_func=lambda paciente: paciente['nome'])
    data_sessao = st.date_input("Data da Sessão")
    notas = st.text_area("Notas da Sessão")

    if st.button("Registrar Sessão"):
        registrar_sessao_terapia(paciente_selecionado['id'], data_sessao, notas)
        st.success("Sessão registrada com sucesso!")


# ### Gerenciamento de Prontuários

# In[5]:


def criar_atualizar_prontuario(paciente_id, conteudo):
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO prontuarios (paciente_id, conteudo)
            VALUES (?, ?)
            ON CONFLICT(paciente_id) DO UPDATE SET conteudo=excluded.conteudo
            """,
            (paciente_id, conteudo)
        )
        conn.commit()

def buscar_prontuarios(palavra_chave):
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM prontuarios WHERE conteudo LIKE ?", ('%' + palavra_chave + '%',))
        prontuarios = cursor.fetchall()
    return prontuarios

def buscar_pacientes():
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id, nome FROM pacientes")
        pacientes = cursor.fetchall()
    return pacientes

def pagina_gerenciamento_prontuarios():
    st.title("Gerenciamento de Prontuários")

    # Interface para busca de prontuários
    palavra_chave = st.text_input("Palavra-chave para busca")
    if st.button("Buscar"):
        resultados = buscar_prontuarios(palavra_chave)
        for prontuario in resultados:
            st.write(f"ID: {prontuario['id']}, Conteúdo: {prontuario['conteudo']}")

    # Interface para criação ou atualização de prontuário
    paciente_id = st.selectbox("Selecione o Paciente", [(p['id'], p['nome']) for p in buscar_pacientes()], format_func=lambda x: x[1])
    conteudo = st.text_area("Conteúdo do Prontuário")
    if st.button("Salvar Prontuário"):
        criar_atualizar_prontuario(paciente_id, conteudo)
        st.success("Prontuário atualizado com sucesso!")


# ### Implementação de Relatórios Personalizados

# #### API OPENAI usando chat.completions()

# In[ ]:


# Configuração do logging para registrar erros em um arquivo
logging.basicConfig(filename='app_errors.log', level=logging.ERROR,
                    format='%(asctime)s - %(levelname)s - %(message)s', encoding='utf-8')

# Carregue a chave de API da variável de ambiente
#_ = load_dotenv(find_dotenv())


# Carrega a API key dos secrets do Streamlit
api_key = st.secrets["OPENAI_API_KEY"]


#client = openai.Client()


client = OpenAI(api_key=api_key)


if client is None:
    error_message = "A chave de API da OpenAI não foi encontrada. Certifique-se de que a variável de ambiente 'OPENAI_API_KEY' está definida."
    logging.error(error_message)
# Configuração do logging para registrar erros em um arquivo
logging.basicConfig(filename='app_errors.log', level=logging.ERROR,
                    format='%(asctime)s - %(levelname)s - %(message)s')

# Carregue a chave de API da variável de ambiente
#openai.api_key = os.getenv('OPENAI_API_KEY')
_ = load_dotenv(find_dotenv())

client = openai.Client()

if client is None:
    error_message = "A chave de API da OpenAI não foi encontrada. Certifique-se de que a variável de ambiente 'OPENAI_API_KEY' está definida."
    logging.error(error_message)
    raise ValueError(error_message)

# Função para conectar ao banco de dados
def connect_db():
    try:
        conn = sqlite3.connect('database.db')
        conn.row_factory = sqlite3.Row  # Permite acessar colunas pelo nome
        return conn
    except sqlite3.Error as e:
        error_message = f"Erro ao conectar ao banco de dados: {e}"
        logging.error(error_message)
        raise ConnectionError(error_message)

# Função para recuperar dados do paciente
def get_patient_data(paciente_id):
    conn = None
    try:
        conn = connect_db()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM pacientes WHERE id = ?", (paciente_id,))
        paciente_info = cursor.fetchone()
        if not paciente_info:
            error_message = f"Paciente com ID {paciente_id} não encontrado."
            logging.error(error_message)
            raise ValueError(error_message)
        
        # Converter paciente_info em um dicionário
        paciente_info = dict(paciente_info)
        
        # Verificar e converter a data de nascimento para o formato esperado
        data_nascimento = paciente_info['data_nascimento']
        try:
            data_nascimento = datetime.strptime(data_nascimento, '%Y-%m-%d')
        except ValueError:
            data_nascimento = datetime.strptime(data_nascimento, '%d-%m-%Y')
        
        paciente_info['data_nascimento'] = data_nascimento.strftime('%Y-%m-%d')

        cursor.execute("SELECT * FROM sessoes_terapia WHERE paciente_id = ?", (paciente_id,))
        sessoes_info = cursor.fetchall()
        
        # Converter sessoes_info em uma lista de dicionários, se necessário modificar
        sessoes_info = [dict(sessao) for sessao in sessoes_info]
        
        return paciente_info, sessoes_info
    except sqlite3.Error as e:
        error_message = f"Erro ao buscar dados do paciente: {e}"
        logging.error(error_message)
        raise Exception(error_message)
    finally:
        if conn:
            conn.close()

# Função para gerar relatórios e laudos utilizando a API da OpenAI
def generate_report(paciente_id):
    try:
        paciente_info, sessoes_info = get_patient_data(paciente_id)
        
        # Calcular a idade do paciente
        data_nascimento = datetime.strptime(paciente_info['data_nascimento'], '%Y-%m-%d')
        hoje = datetime.now()
        idade_anos = hoje.year - data_nascimento.year - ((hoje.month, hoje.day) < (data_nascimento.month, data_nascimento.day))
        idade_meses = hoje.month - data_nascimento.month - (hoje.day < data_nascimento.day)
        if idade_meses < 0:
            idade_meses += 12
            idade_anos -= 1

        idade_formatada = f"{idade_anos} anos e {idade_meses} meses"

        consulta_text = f"Atestado Neuropsicológico\n\nNome: {paciente_info['nome']}\nData de Nascimento: {paciente_info['data_nascimento']}\nIdade: {idade_formatada}\n\nAnamnese: {paciente_info['historico_medico']}\nHistórico Familiar: {paciente_info['historico_familiar']}"
        for sessao in sessoes_info:
            consulta_text += f"\nSessão em {sessao['data_sessao']}: {sessao['notas']}"

        # Pedido para a API da OpenAI
        response = client.chat.completions.create(
            model="gpt-4o-2024-08-06",
            messages=[
                {"role": "system", "content": """Aja como um neuropsicólogo clínico especializado em gerar relatórios médicos profissionais. 
                 Sua tarefa é elaborar um Atestado Neuropsicológico com base nas informações recuperadas do banco de dados do paciente. 
                 Utilize as referências ao DSM-5-TR e CID-11 com sua nova classificações conforme apropriado e estrutura a seguir: 
                 - Descrição da demanda: Apresente o motivo da avaliação neuropsicológica, descrevendo os sintomas ou queixas relatadas, 
                 além do contexto clínico. 
                 - Procedimentos: Descreva os testes neuropsicológicos realizados e os procedimentos usados para avaliar o paciente. 
                 - Análise: Faça uma análise detalhada dos resultados dos testes, correlacionando com os sintomas descritos, 
                 e utilizando critérios diagnósticos do DSM-5-TR e CID-11. 
                 - Conclusão: Ofereça um diagnóstico claro, recomendações de tratamento, encaminhamentos necessários e considerações clínicas. 
                 As recomendações devem incluir intervenções terapêuticas ou sugestões de acompanhamento psicológico ou psiquiátrico. 
                 - Referências: Inclua as referências dos instrumentos e critérios diagnósticos utilizados, como o DSM-5-TR e CID-11. 
                 O relatório deve ter um tom profissional, mas acessível, balanceando termos técnicos com explicações claras para os leigos."""},
                {"role": "user", "content": consulta_text}
            ],
            max_tokens=2000,
            temperature=0.5,
            presence_penalty=0.5,
            frequency_penalty=0.5
        )
        # Acessar a resposta gerada
        laudo_text = response.choices[0].message.content.strip()
        
        return f"Relatório para {paciente_info['nome']} - {datetime.now().date()}:\n{laudo_text}"
    
    except OpenAIError as e:
        error_message = f"Erro na API da OpenAI: {e}"
        logging.error(error_message)
        raise Exception("Erro ao gerar relatório devido a problemas com a API da OpenAI.")
    except Exception as e:
        error_message = f"Erro ao gerar relatório: {e}"
        logging.error(error_message)
        raise Exception(error_message)
    
# Função para exibir o frontend no Streamlit
def pagina_gerar_relatorio():
    st.title("Gerar Relatórios e Laudos")

    # Conectar ao banco para pegar os pacientes disponíveis
    try:
        with connect_db() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT id, nome FROM pacientes")
            pacientes = cursor.fetchall()

        # Converter os resultados para uma lista de dicionários
        pacientes_list = [{"id": paciente["id"], "nome": paciente["nome"]} for paciente in pacientes]

        # Se houver pacientes, exibir no frontend para seleção
        if pacientes_list:
            paciente_selecionado = st.selectbox(
                "Selecione o Paciente", 
                pacientes_list, 
                format_func=lambda paciente: paciente["nome"]
            )

            if st.button("Gerar Relatório"):
                try:
                    # Chamar a função para gerar o relatório do paciente selecionado
                    report = generate_report(paciente_selecionado['id'])
                    st.subheader("Relatório Gerado")
                    st.write(report)
                except Exception as e:
                    st.error(f"Ocorreu um erro ao gerar o relatório: {e}")
                    logging.error(f"Erro ao gerar relatório para o paciente {paciente_selecionado['id']}: {e}")
        else:
            st.warning("Nenhum paciente cadastrado.")

    except sqlite3.Error as e:
        st.error(f"Erro ao buscar pacientes: {e}")
        logging.error(f"Erro ao buscar pacientes no banco de dados: {e}")


# ### Função Principal para Escolher a Página

# In[ ]:


def main():
    #st.sidebar.image("Imagem 1_20240920222448_00.jpg", caption="Willian Rodrigues Sally Caetano - Psicólogo Clínico")

    st.sidebar.markdown(
        "<h1 style='text-align: center;'>Selecione o Serviço</h3>",
        unsafe_allow_html=True
    )

    st.sidebar.divider()

    # Inject CSS to style the buttons and hover effects
    st.sidebar.markdown(
        """
        <style>
        div.stButton > button {
            width: 100%;
            text-align: center;
        }
        div.stButton > button:hover {
            border-color: #28a745;
            color: #28a745;
        }
        </style>
        """,
        unsafe_allow_html=True
    )

    st.image("Imagem 1_20240920222448_00.jpg", caption="Willian Rodrigues Sally Caetano - Psicólogo Clínico")


    # Lista de opções e funções correspondentes
    opcoes = [
        ("Cadastro de Pacientes", pagina_cadastro_pacientes),
        ("Registro de Sessões de Terapia", pagina_registro_sessoes),
        ("Gerenciamento de Prontuários", pagina_gerenciamento_prontuarios),
        ("Agendar Consulta", pagina_agendar_consulta),
        ("Gerar Relatórios e Laudos", pagina_gerar_relatorio)
    ]

    # Inicializa a opção selecionada
    if 'pagina' not in st.session_state:
        st.session_state.pagina = None

    # Cria botões para cada opção
    for nome, funcao in opcoes:
        if st.sidebar.button(nome):
            st.session_state.pagina = nome

    st.sidebar.divider()

    st.sidebar.markdown(
            """
            <div class="sidebar-footer">
            <p style='text-align: center;'>
                Desenvolvido por <a href="https://www.instagram.com/datasage_ai/profilecard/?igsh=MWlzN2cwdnZjaGliZA==" target="_blank">DataSage AI</a>
            </div>
            """,
            unsafe_allow_html=True
        )        

    # Chama a função correspondente à opção selecionada
    if st.session_state.pagina == "Cadastro de Pacientes":
        pagina_cadastro_pacientes()
    elif st.session_state.pagina == "Registro de Sessões de Terapia":
        pagina_registro_sessoes()
    elif st.session_state.pagina == "Gerenciamento de Prontuários":
        pagina_gerenciamento_prontuarios()
    elif st.session_state.pagina == "Agendar Consulta":
        pagina_agendar_consulta()
    elif st.session_state.pagina == "Gerar Relatórios e Laudos":
        pagina_gerar_relatorio()
    



if __name__ == "__main__":
    main()


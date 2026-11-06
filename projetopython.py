import hashlib
import hmac
import os
import secrets
import sqlite3
import unicodedata
from datetime import datetime

from tkcalendar import Calendar, DateEntry
from tkinter import *
from tkinter.font import Font
from tkinter.messagebox import *
from tkinter import filedialog
from tkinter.ttk import Combobox, Notebook, Treeview

# =======================================
# CONFIGURAÇÕES
# =======================================
# O banco fica na mesma pasta deste arquivo .py, não importa de onde o
# programa seja executado. Se você já criou o gerenciador.db com o script
# SQL, coloque-o nesta pasta.
PASTA = os.path.dirname(os.path.abspath(__file__))
CAMINHO_DB = os.path.join(PASTA, "gerenciador.db")

# Imagem do banner (precisa estar na mesma pasta deste arquivo .py)
CAMINHO_BANNER = os.path.join(PASTA, "banner.png")

# Valores fixos (os mesmos do CHECK da tabela tarefa no script SQL)
PRIORIDADES = ("Baixa", "Média", "Alta")
CORES = {"Baixa": "green", "Média": "orange", "Alta": "red"}

# No banco, status é INT: 0 = pendente, 1 = concluída
STATUS_PENDENTE = 0
STATUS_CONCLUIDA = 1
NOME_STATUS = {STATUS_PENDENTE: "Pendente", STATUS_CONCLUIDA: "Concluída"}

# Disciplinas garantidas no banco. Toda vez que o programa abre, as que ainda
# não existem são cadastradas (as que já existem não são alteradas nem repetidas).
DISCIPLINAS_PADRAO = (
    "Banco de Dados I",
    "Linguagem de Programação II",
    "Modelagem de Dados II",
    "Matemática",
    "Português",
    "Inglês",
    "Artes",
    "Educação Física",
    "Biologia",
    "Física",
    "Química",
    "História",
    "Geografia",
    "Filosofia",
    "Sociologia",
    "Ferramentas para WEB II",
    "Montagem e manutenção de computadores",
)

# Ordena Alta > Média > Baixa (usado nos SELECT; a tabela tarefa tem o apelido t)
ORDEM_PRIORIDADE = "CASE t.prioridade WHEN 'Alta' THEN 1 WHEN 'Média' THEN 2 ELSE 3 END"


# =======================================
# BANCO DE DADOS
# =======================================
def conectar():
    conexao = sqlite3.connect(CAMINHO_DB)
    # O SQLite deixa as chaves estrangeiras desligadas por padrão
    conexao.execute("PRAGMA foreign_keys = ON")
    return conexao


def _chave(nome):
    """Nome sem acentos, sem maiúsculas e sem espaços nas pontas (para comparar)."""
    decomposto = unicodedata.normalize("NFD", nome)
    sem_acento = "".join(c for c in decomposto if unicodedata.category(c) != "Mn")
    return sem_acento.casefold().strip()


def criarBanco():
    """Cria as tabelas (mesma estrutura da Etapa 2 do script SQL), se não existirem."""
    conexao = conectar()
    try:
        conexao.executescript("""
            CREATE TABLE IF NOT EXISTS disciplina (
                id_disciplina INTEGER      PRIMARY KEY AUTOINCREMENT,
                descricao     VARCHAR(100) NOT NULL 
            );

            CREATE TABLE IF NOT EXISTS aluno (
                id_aluno  INTEGER      PRIMARY KEY AUTOINCREMENT,
                usuario   VARCHAR(50)  NOT NULL,
                senha     VARCHAR(255) NOT NULL,
                matricula INT          NOT NULL UNIQUE
            );

            CREATE TABLE IF NOT EXISTS tarefa (
                id_tarefa     INTEGER      PRIMARY KEY AUTOINCREMENT,
                titulo_tarefa VARCHAR(100) NOT NULL,
                descricao     VARCHAR(255),
                prazo         DATE         NOT NULL,
                prioridade    VARCHAR(10)  NOT NULL
                              CHECK (prioridade IN ('Alta','Média','Baixa')),
                status        INT          NOT NULL DEFAULT 0
                              CHECK (status IN (0,1)),
                id_aluno      INT          NOT NULL,
                id_disciplina INT          NOT NULL,
                FOREIGN KEY (id_aluno)      REFERENCES aluno(id_aluno)
                    ON UPDATE CASCADE ON DELETE CASCADE,
                FOREIGN KEY (id_disciplina) REFERENCES disciplina(id_disciplina)
                    ON UPDATE CASCADE ON DELETE RESTRICT
            );

            CREATE TABLE IF NOT EXISTS resumo (
                id_resumo     INTEGER       PRIMARY KEY AUTOINCREMENT,
                titulo_resumo VARCHAR(100)  NOT NULL,
                conteudo      VARCHAR(2000) NOT NULL,
                id_aluno      INT           NOT NULL,
                id_disciplina INT           NOT NULL,
                FOREIGN KEY (id_aluno)      REFERENCES aluno(id_aluno)
                    ON UPDATE CASCADE ON DELETE CASCADE,
                FOREIGN KEY (id_disciplina) REFERENCES disciplina(id_disciplina)
                    ON UPDATE CASCADE ON DELETE RESTRICT
            );

            CREATE TABLE IF NOT EXISTS flashcard (
                id_flashcard INTEGER      PRIMARY KEY AUTOINCREMENT,
                pergunta     VARCHAR(255) NOT NULL,
                resposta     VARCHAR(500) NOT NULL,
                id_resumo    INT          NOT NULL,
                FOREIGN KEY (id_resumo) REFERENCES resumo(id_resumo)
                    ON UPDATE CASCADE ON DELETE CASCADE
            );
        """)

        # Cadastra as disciplinas que ainda não existem. A comparação ignora
        # maiúsculas e acentos, porque o UNIQUE do SQLite diferencia

        existentes = {_chave(linha[0])
                      for linha in conexao.execute("SELECT descricao FROM disciplina")}
        for nome in DISCIPLINAS_PADRAO:
            if _chave(nome) not in existentes:
                conexao.execute("INSERT INTO disciplina (descricao) VALUES (?)", (nome,))
                existentes.add(_chave(nome))
        conexao.commit()
    finally:
        conexao.close()


def gerarHash(senha):
    """Transforma a senha em 'pbkdf2$sal$hash' (cabe nos 255 caracteres da coluna)."""
    sal = secrets.token_hex(16)
    resumo = hashlib.pbkdf2_hmac(
        "sha256", senha.encode("utf-8"), bytes.fromhex(sal), 200_000
    ).hex()
    return f"pbkdf2${sal}${resumo}"


def verificarSenha(senha, armazenada):
    if armazenada.startswith("pbkdf2$"):
        try:
            _, sal, resumo = armazenada.split("$")
            calculado = hashlib.pbkdf2_hmac(
                "sha256", senha.encode("utf-8"), bytes.fromhex(sal), 200_000
            ).hex()
        except ValueError:
            return False
        return hmac.compare_digest(calculado, resumo)

    # Valor sem esse formato (ex.: os dados de teste do script SQL, como
    # 'hash_ana_123'): compara direto
    return hmac.compare_digest(senha.encode("utf-8"), armazenada.encode("utf-8"))


def carregarDisciplinas():
    """Devolve {descrição: id_disciplina}, em ordem alfabética."""
    conexao = conectar()
    try:
        linhas = conexao.execute(
            "SELECT id_disciplina, descricao FROM disciplina ORDER BY descricao"
        ).fetchall()
    finally:
        conexao.close()
    return {descricao: id_disciplina for id_disciplina, descricao in linhas}


# =======================================
# CLASSE ALUNO
# =======================================
class Aluno:
    def __init__(self, usuario, senha, matricula):
        self.usuario = usuario
        self.senha = senha
        self.matricula = matricula


# =======================================
# CLASSE TAREFA
# =======================================
class Tarefa:
    def __init__(self, titulo, descricao, prazo, prioridade, status):
        self.titulo = titulo
        self.descricao = descricao
        self.prazo = prazo
        self.prioridade = prioridade
        self.status = status


# =======================================
# CLASSE DA INTERFACE
# =======================================
class Login(Frame):
    def __init__(self):
        Frame.__init__(self)

        # Aluno que entrou no sistema (None enquanto ninguém fez login)
        self.idAluno = None
        self.usuarioLogado = None
        
# *=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=
# JANELA DE LOGIN
    
        self.master.title("LOGIN")
        self.master.geometry("650x350")

        # Faz o Frame ocupar a janela inteira
        self.master.columnconfigure(0, weight=1)
        self.master.rowconfigure(0, weight=1)
        self.grid(row=0, column=0, sticky="nsew")

        # Divide a janela em 3 linhas: banner (1/6), conteúdo (4/6), banner (1/6)
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1, uniform="area")
        self.rowconfigure(1, weight=4, uniform="area")
        self.rowconfigure(2, weight=1, uniform="area")

        # IMAGEM DO BANNER (PNG lido direto pelo Tkinter, sem Pillow)
        # O ideal é o banner.png ter 650 x 58 pixels.
        # Se der erro, o motivo aparece no terminal e o texto "BANNER" continua.
        self.fotoBanner = None
        try:
            self.fotoBanner = PhotoImage(file=CAMINHO_BANNER, master=self.master)
        except Exception as erro:
            print("Não foi possível carregar o banner:", CAMINHO_BANNER)
            print("Motivo:", repr(erro))

        # BANNER DE CIMA
        self.bannerTopo = Label(self, text="BANNER", bg="gray", fg="white",
                                image=self.fotoBanner, borderwidth=0)
        self.bannerTopo.grid(row=0, column=0, sticky="nsew")

        # BANNER DE BAIXO
        self.bannerBase = Label(self, text="BANNER", bg="gray", fg="white",
                                image=self.fotoBanner, borderwidth=0)
        self.bannerBase.grid(row=2, column=0, sticky="nsew")

        
        # ÁREA DO CONTEÚDO: colado no topo, com 15 px de distância do banner
        self.conteudo = Frame(self)
        self.conteudo.grid(row=1, column=0, sticky="n", pady=(15, 0))

        fonte1 = Font(
            family="Times New Roman",
            size=16,
            slant="italic",
            weight = "bold"
        )

        # TÍTULO (ocupa as duas colunas para ficar centralizado)
        self.lblTexto1 = Label(self.conteudo)
        self.lblTexto1["font"] = fonte1
        self.lblTexto1["text"] = "Tela de login do usuário"
        self.lblTexto1["fg"] = "blue2"
        self.lblTexto1.grid(row=0, column=0, columnspan=2, padx=5, pady=5)

        

# =======================================
# USUÁRIO
# =======================================
        self.lblUsuario = Label(self.conteudo)
        self.lblUsuario["text"] = "Usuário:"
        self.lblUsuario.grid(row=1, column=0, padx=5, pady=5, sticky="e")

        self.usuario = Entry(self.conteudo)
        self.usuario.grid(row=1, column=1, padx=5, pady=5)

# =======================================
# SENHA
# =======================================
        self.lblSenha = Label(self.conteudo)
        self.lblSenha["text"] = "Senha:"
        self.lblSenha.grid(row=2, column=0, padx=5, pady=5, sticky="e")

        self.senha = Entry(self.conteudo, show="*")
        self.senha.grid(row=2, column=1, padx=5, pady=5)

# =======================================
# MATRÍCULA
# =======================================
        self.lblMatricula = Label(self.conteudo)
        self.lblMatricula["text"] = "Matrícula:"
        self.lblMatricula.grid(row=3, column=0, padx=5, pady=5, sticky="e")

        self.matricula = Entry(self.conteudo)
        self.matricula.grid(row=3, column=1, padx=5, pady=5)

# =======================================
# BOTÃO ENTRAR
# =======================================
        self.btnEntrar = Button(self.conteudo, width=12)
        self.btnEntrar["text"] = "Entrar"
        self.btnEntrar["command"] = self.entrar
        self.btnEntrar.grid(row=4, column=0, padx=5, pady=10, sticky="e")

# =======================================
# BOTÃO CADASTRAR (abre a janela de cadastro)
# =======================================
        self.btnCadastrar = Button(self.conteudo, width=12)
        self.btnCadastrar["text"] = "Cadastrar"
        self.btnCadastrar["command"] = self.abrirCadastro
        self.btnCadastrar.grid(row=4, column=1, padx=5, pady=10, sticky="w")

        
        self.master.bind("<Return>", lambda evento: self.entrar()) #Login no ENTER
        self.usuario.focus_set()

# *=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=
# FUNÇÕES AUXILIARES

    def _jaAberta(self, nome):
        """Se a janela já está aberta, traz ela para a frente e devolve True."""
        janela = getattr(self, nome, None)
        if janela is not None and janela.winfo_exists():
            janela.lift()
            janela.focus_force()
            return True
        return False

# *=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=
# FUNÇÕES DO CADASTRO

    def entrar(self):
        usuario = self.usuario.get().strip()
        senha = self.senha.get()
        matricula = self.matricula.get().strip()

        try:
            if not usuario or not senha or not matricula:
                raise ValueError("Preencha usuário, senha e matrícula.")

            if not matricula.isdecimal() or len(matricula) > 12:
                raise ValueError("A matrícula deve conter apenas números (até 12 dígitos).")

            conexao = conectar()
            try:
                linha = conexao.execute(
                    "SELECT id_aluno, senha FROM aluno WHERE usuario = ? AND matricula = ?",
                    (usuario, int(matricula))
                ).fetchone()   # None se não encontrou
            finally:
                conexao.close()

            if linha is None or not verificarSenha(senha, linha[1]): # Mensagem única, para não revelar qual dos três dados está errado
                raise ValueError("Usuário, senha ou matrícula incorretos.")

            self.idAluno = linha[0]
            self.usuarioLogado = usuario

            # Limpa os campos e passa para o menu
            self.usuario.delete(0, END) 
            self.senha.delete(0, END)
            self.matricula.delete(0, END)

            self.master.withdraw()   # esconde a janela de login
            self.menu()

        except ValueError as erro:
            showerror("Login", str(erro), parent=self)
        except sqlite3.Error as erro:
            showerror("Erro no banco de dados", str(erro), parent=self)

    def sair(self):
        # Fecha todas as janelas abertas depois do login
        for nome in ("janelaTarefa", "janelaListar", "janelaEditar",
                     "janelaConcluir", "janelaResumo", "janelaRelatorio", "janelaMenu"):
            janela = getattr(self, nome, None)
            if janela is not None and janela.winfo_exists():
                janela.destroy()

        self.idAluno = None
        self.usuarioLogado = None

        # Volta para a tela de login
        self.master.deiconify()
        self.usuario.focus_set()

# *=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=
# JANELA DE CADASTRO

    def abrirCadastro(self):
        if self._jaAberta("janelaCadastro"):
            return

        self.janelaCadastro = Toplevel(self)
        self.janelaCadastro.title("CADASTRO")
        self.janelaCadastro.geometry("400x300")

        self.janelaCadastro.columnconfigure(0, weight=1)
        self.janelaCadastro.rowconfigure(0, weight=1)

        caixa = Frame(self.janelaCadastro)
        caixa.grid(row=0, column=0)

        fonte = Font(family="Times New Roman", size=16, slant="italic")
        Label(caixa, text="Cadastro de usuário", font=fonte, fg="blue",
              bg="lightgray").grid(row=0, column=0, columnspan=2, padx=5, pady=(0, 10))
        
# =======================================
# USUÁRIO
# =======================================
        Label(caixa, text="Usuário:").grid(row=1, column=0, padx=5, pady=5, sticky="e")
        self.cadUsuario = Entry(caixa)
        self.cadUsuario.grid(row=1, column=1, padx=5, pady=5)
        
# =======================================
# SENHA
# =======================================
        Label(caixa, text="Senha:").grid(row=2, column=0, padx=5, pady=5, sticky="e")
        self.cadSenha = Entry(caixa, show="*")
        self.cadSenha.grid(row=2, column=1, padx=5, pady=5)
        
# =======================================
# MATRÍCULA
# =======================================
        Label(caixa, text="Matrícula:").grid(row=3, column=0, padx=5, pady=5, sticky="e")
        self.cadMatricula = Entry(caixa)
        self.cadMatricula.grid(row=3, column=1, padx=5, pady=5)
        
# =======================================
# BOTÃO CADASTRAR
# =======================================
        Button(caixa, text="Cadastrar", width=20, command=self.cadastrar).grid(
            row=4, column=0, columnspan=2, pady=15)

        self.janelaCadastro.bind("<Return>", lambda evento: self.cadastrar())
        self.cadUsuario.focus_set()

    def cadastrar(self):
        usuario = self.cadUsuario.get().strip()
        senha = self.cadSenha.get()
        matricula = self.cadMatricula.get().strip()

        try:
            if not usuario:
                raise ValueError("Informe o nome de usuário.")

            if len(usuario) > 50:
                raise ValueError("O usuário pode ter no máximo 50 caracteres.")

            if not senha:
                raise ValueError("Informe a senha.")

            if not matricula.isdecimal() or len(matricula) > 12:
                raise ValueError("A matrícula deve conter apenas números (até 12 dígitos).")

            conexao = conectar()
            try:
                conexao.execute(
                    "INSERT INTO aluno (usuario, senha, matricula) VALUES (?, ?, ?)",
                    (usuario, gerarHash(senha), int(matricula))
                )
                conexao.commit()
            finally:
                conexao.close()

            showinfo("Cadastro", "Usuário cadastrado com sucesso!",
                     parent=self.janelaCadastro)

            # Fecha o cadastro e já deixa o usuário preenchido no login
            self.janelaCadastro.destroy()
            self.usuario.delete(0, END)
            self.usuario.insert(0, usuario)
            self.senha.focus_set()

        except ValueError as erro:
            showerror("Dados inválidos", str(erro), parent=self.janelaCadastro)

        except sqlite3.IntegrityError as erro:
            # A mensagem do SQLite diz qual coluna UNIQUE foi violada
            if "aluno.usuario" in str(erro):
                texto = "Já existe um usuário com esse nome."
            elif "aluno.matricula" in str(erro):
                texto = "Já existe um usuário com essa matrícula."
            else:
                texto = str(erro)
            showerror("Cadastro", texto, parent=self.janelaCadastro)

        except sqlite3.Error as erro:
            showerror("Erro no banco de dados", str(erro), parent=self.janelaCadastro)

# *=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=
# JANELA DO MENU

    def menu(self):
        if self._jaAberta("janelaMenu"):
            return

        self.janelaMenu = Toplevel(self)
        self.janelaMenu.title("MENU")
        self.janelaMenu.geometry("500x480")

        
        self.janelaMenu.protocol("WM_DELETE_WINDOW", self.sair)# Fechar o menu pelo X também faz logout

        self.janelaMenu.columnconfigure(0, weight=1)
        self.janelaMenu.rowconfigure(0, weight=1)

        # Frame que agrupa os botões (este é o que fica centralizado)
        caixa = Frame(self.janelaMenu)
        caixa.grid(row=0, column=0)

        Label(caixa, text=f"Olá, {self.usuarioLogado}!",
              font=("Verdana", 12)).grid(row=0, column=0, pady=(0, 10))
        
# =======================================
# BOTÃO ADICIONAR TAREFA
# =======================================
        self.btnAdicionar = Button(caixa, width=20)
        self.btnAdicionar["text"] = "Adicionar tarefa(s)"
        self.btnAdicionar["command"] = self.AdicionarTarefa
        self.btnAdicionar.grid(row=1, column=0, pady=10)

# =======================================
# BOTÃO LISTAR TAREFA
# =======================================
        self.btnListar = Button(caixa, width=20)
        self.btnListar["text"] = "Listar tarefa(s)"
        self.btnListar["command"] = self.ListarTarefa
        self.btnListar.grid(row=2, column=0, pady=10)

    # =======================================
    # BOTÃO EDITAR TAREFA
    # =======================================
        self.btnEditar = Button(caixa, width=20)
        self.btnEditar["text"] = "Editar tarefa(s)"
        self.btnEditar["command"] = self.EditarTarefa
        self.btnEditar.grid(row=3, column=0, pady=10)

# =======================================
# BOTÃO MARCAR COMO CONCLUÍDA
# =======================================
        self.btnMarcar = Button(caixa, width=20)
        self.btnMarcar["text"] = "Marcar como concluída"
        self.btnMarcar["command"] = self.MarcarConcluida
        self.btnMarcar.grid(row=4, column=0, pady=10)

# =======================================
# BOTÃO RESUMO
# =======================================
        self.btnResumo = Button(caixa, width=20)
        self.btnResumo["text"] = "Resumo / Flash Cards"
        self.btnResumo["command"] = self.Resumo
        self.btnResumo.grid(row=5, column=0, pady=10)

# =======================================
# BOTÃO GERAR RELATÓRIO
# =======================================
        self.btnRelatorio = Button(caixa, width=20)
        self.btnRelatorio["text"] = "Gerar relatório"
        self.btnRelatorio["command"] = self.gerarRelatorio
        self.btnRelatorio.grid(row=6, column=0, pady=10)

# =======================================
# BOTÃO SAIR
# =======================================
        self.btnSair = Button(caixa, width=20)
        self.btnSair["text"] = "Sair"
        self.btnSair["command"] = self.sair
        self.btnSair.grid(row=7, column=0, pady=(20, 10))

# *=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=
# JANELA ADD TAREFA

    def AdicionarTarefa(self):
        if self._jaAberta("janelaTarefa"):
            return

        self.janelaTarefa = Toplevel(self)
        self.janelaTarefa.title("ADICIONAR TAREFA")
        self.janelaTarefa.geometry("500x480")

        self.janelaTarefa.columnconfigure(0, weight=1)
        self.janelaTarefa.rowconfigure(0, weight=1)

        # Frame que agrupa os campos (fica centralizado)
        caixa = Frame(self.janelaTarefa)
        caixa.grid(row=0, column=0)

# =======================================
# TÍTULO
# =======================================
        Label(caixa, text="Título:").grid(row=0, column=0, padx=5, pady=5, sticky="e")
        self.titulo = Entry(caixa, width=30)
        self.titulo.grid(row=0, column=1, padx=5, pady=5)
        
# =======================================
# DESCRIÇÃO
# =======================================
        Label(caixa, text="Descrição:").grid(row=1, column=0, padx=5, pady=5, sticky="e")
        self.descricao = Entry(caixa, width=30)
        self.descricao.grid(row=1, column=1, padx=5, pady=5)

# =======================================
# PRAZO
# =======================================
        Label(caixa, text="Prazo:").grid(row=2, column=0, padx=5, pady=5, sticky="e")
        self.prazo = DateEntry(caixa, date_pattern="dd/mm/yyyy", state="readonly")
        self.prazo.grid(row=2, column=1, padx=5, pady=5, sticky="w")

# =======================================
# PRIORIDADE
# =======================================
        Label(caixa, text="Prioridade:").grid(row=3, column=0, padx=5, pady=5, sticky="e")
        self.prioridade = Combobox(caixa, values=PRIORIDADES, state="readonly")
        self.prioridade.current(0)
        self.prioridade.grid(row=3, column=1, padx=5, pady=5, sticky="w")

# =======================================
# DISCIPLINA 
# =======================================
        Label(caixa, text="Disciplina:").grid(row=4, column=0, padx=5, pady=5, sticky="e")
        self.mapaDisc = carregarDisciplinas()
        self.disciplina = Combobox(caixa, values=list(self.mapaDisc), state="readonly",
                                   width=38)
        if self.mapaDisc:
            self.disciplina.current(0)
        self.disciplina.grid(row=4, column=1, padx=5, pady=5, sticky="w")

# =======================================
# BOTÃO SALVAR
# =======================================
        self.btnSalvar = Button(caixa, text="Salvar tarefa", width=20,
                                command=self.salvarTarefa)
        self.btnSalvar.grid(row=5, column=0, columnspan=2, pady=15)


    def salvarTarefa(self):
        titulo = self.titulo.get().strip()
        descricao = self.descricao.get().strip()
        prioridade = self.prioridade.get()
        disciplina = self.disciplina.get()

        try:
            if not titulo:
                raise ValueError("Informe o título da tarefa.")

            if len(titulo) > 100:
                raise ValueError("O título pode ter no máximo 100 caracteres.")

            if len(descricao) > 255:
                raise ValueError("A descrição pode ter no máximo 255 caracteres.")

            if disciplina not in self.mapaDisc:
                raise ValueError("Selecione a disciplina.")

            # Converte dd/mm/aaaa para aaaa-mm-dd (formato do campo DATE)
            prazo = datetime.strptime(self.prazo.get(), "%d/%m/%Y").strftime("%Y-%m-%d")

            conexao = conectar()
            try:
                # status não é informado: o banco usa o padrão 0 (pendente)
                conexao.execute(
                    "INSERT INTO tarefa "
                    "(titulo_tarefa, descricao, prazo, prioridade, id_aluno, id_disciplina) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (titulo, descricao, prazo, prioridade,
                     self.idAluno, self.mapaDisc[disciplina])
                )
                conexao.commit()
            finally:
                conexao.close()

            showinfo("Tarefa", "Tarefa cadastrada com sucesso!",
                     parent=self.janelaTarefa)
            self.titulo.delete(0, END)
            self.descricao.delete(0, END)

        except ValueError as erro:
            showerror("Dados inválidos", str(erro), parent=self.janelaTarefa)
        except sqlite3.Error as erro:
            showerror("Erro no banco de dados", str(erro), parent=self.janelaTarefa)

# *=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=
# JANELA LISTAR TAREFA

    def ListarTarefa(self):
        if self._jaAberta("janelaListar"):
            return

        self.janelaListar = Toplevel(self)
        self.janelaListar.title("LISTAR TAREFAS")
        self.janelaListar.geometry("780x650")

        self.janelaListar.columnconfigure(0, weight=1)
        self.janelaListar.rowconfigure(2, weight=1)  # a lista ocupa o espaço que sobra

# =======================================
# CALENDÁRIO
# =======================================
        self.calendario = Calendar(self.janelaListar, date_pattern="dd/mm/yyyy",
                                   selectmode="none")
        self.calendario.grid(row=0, column=0, padx=10, pady=10)

        # Cada prioridade vira uma "tag" com a sua cor
        for prioridade, cor in CORES.items():
            self.calendario.tag_config(prioridade, background=cor, foreground="white")

# =======================================
# FILTRO POR PRIORIDADE
# =======================================
        filtro = Frame(self.janelaListar)
        filtro.grid(row=1, column=0, pady=5)

        Label(filtro, text="Prioridade:").grid(row=0, column=0, padx=5)
        self.filtroPrioridade = Combobox(filtro, values=("Todas",) + PRIORIDADES,
                                         state="readonly")
        self.filtroPrioridade.current(0)
        self.filtroPrioridade.grid(row=0, column=1, padx=5)
        self.filtroPrioridade.bind("<<ComboboxSelected>>", self.carregarTarefas)

# =======================================
# LISTA COM SCROLLBAR
# =======================================
        quadroLista = Frame(self.janelaListar)
        quadroLista.grid(row=2, column=0, sticky="nsew", padx=10, pady=(0, 10))
        quadroLista.columnconfigure(0, weight=1)
        quadroLista.rowconfigure(0, weight=1)

        self.lista = Treeview(
            quadroLista,
            columns=("titulo", "descricao", "prazo", "prioridade", "disciplina", "status"),
            show="headings",
            selectmode="browse"
        )
        self.lista.heading("titulo", text="Título")
        self.lista.heading("descricao", text="Descrição")
        self.lista.heading("prazo", text="Prazo")
        self.lista.heading("prioridade", text="Prioridade")
        self.lista.heading("disciplina", text="Disciplina")
        self.lista.heading("status", text="Status")
        self.lista.column("titulo", width=130)
        self.lista.column("descricao", width=150)
        self.lista.column("prazo", width=80, anchor="center")
        self.lista.column("prioridade", width=80, anchor="center")
        self.lista.column("disciplina", width=200)
        self.lista.column("status", width=80, anchor="center")
        self.lista.grid(row=0, column=0, sticky="nsew")

        for prioridade, cor in CORES.items():
            self.lista.tag_configure(prioridade, foreground=cor)

        scroll = Scrollbar(quadroLista, orient="vertical", command=self.lista.yview)
        scroll.grid(row=0, column=1, sticky="ns")
        self.lista.configure(yscrollcommand=scroll.set)

        self.carregarTarefas()

    def carregarTarefas(self, evento=None):
        escolhida = self.filtroPrioridade.get()

        # Limpa a lista e os eventos do calendário antes de recarregar
        self.lista.delete(*self.lista.get_children())
        self.calendario.calevent_remove("all")

        sql = ("SELECT t.id_tarefa, t.titulo_tarefa, t.descricao, t.prazo, "
               "t.prioridade, d.descricao, t.status "
               "FROM tarefa t JOIN disciplina d ON d.id_disciplina = t.id_disciplina "
               "WHERE t.id_aluno = ?")
        parametros = [self.idAluno]

        if escolhida != "Todas":
            sql += " AND t.prioridade = ?"
            parametros.append(escolhida)

        sql += " ORDER BY t.prazo"

        conexao = conectar()
        try:
            tarefas = conexao.execute(sql, parametros).fetchall()
        finally:
            conexao.close()

        for id_tarefa, titulo, descricao, prazo, prioridade, disciplina, status in tarefas:
            data = datetime.strptime(prazo, "%Y-%m-%d")

            # Linha na lista (data volta para dd/mm/aaaa)
            # O id da tarefa é usado como identificador da linha (iid)
            self.lista.insert(
                "", END, iid=str(id_tarefa),
                values=(titulo, descricao or "", data.strftime("%d/%m/%Y"),
                        prioridade, disciplina, NOME_STATUS[status]),
                tags=(prioridade,)
            )

            # Data pintada no calendário
            self.calendario.calevent_create(data.date(), titulo, tags=prioridade)

# *=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=
# JANELA EDITAR TAREFA

    def EditarTarefa(self):
        if self._jaAberta("janelaEditar"):
            return

        self.janelaEditar = Toplevel(self)
        self.janelaEditar.title("EDITAR TAREFAS")
        self.janelaEditar.geometry("700x760")

        self.janelaEditar.columnconfigure(0, weight=1)
        self.janelaEditar.rowconfigure(2, weight=1)  # a lista ocupa o espaço que sobra

        # Guarda o id da tarefa que está sendo editada e os dados de cada tarefa
        self.idEditando = None
        self.tarefasEd = {}

        # CALENDÁRIO (mostra os prazos coloridos pela prioridade)
        self.calendarioEd = Calendar(self.janelaEditar, date_pattern="dd/mm/yyyy",
                                     selectmode="none")
        self.calendarioEd.grid(row=0, column=0, padx=10, pady=10)

        for prioridade, cor in CORES.items():
            self.calendarioEd.tag_config(prioridade, background=cor, foreground="white")

# =======================================
# FORMULÁRIO DE EDIÇÃO 
# =======================================
        form = Frame(self.janelaEditar)
        form.grid(row=1, column=0, pady=(0, 10))

        Label(form, text="Título:").grid(row=0, column=0, padx=5, pady=4, sticky="e")
        self.edTitulo = Entry(form, width=30)
        self.edTitulo.grid(row=0, column=1, padx=5, pady=4)

        Label(form, text="Descrição:").grid(row=1, column=0, padx=5, pady=4, sticky="e")
        self.edDescricao = Entry(form, width=30)
        self.edDescricao.grid(row=1, column=1, padx=5, pady=4)

        Label(form, text="Prazo:").grid(row=2, column=0, padx=5, pady=4, sticky="e")
        self.edPrazo = DateEntry(form, date_pattern="dd/mm/yyyy", state="readonly")
        self.edPrazo.grid(row=2, column=1, padx=5, pady=4, sticky="w")

        Label(form, text="Prioridade:").grid(row=3, column=0, padx=5, pady=4, sticky="e")
        self.edPrioridade = Combobox(form, values=PRIORIDADES, state="readonly")
        self.edPrioridade.current(0)
        self.edPrioridade.grid(row=3, column=1, padx=5, pady=4, sticky="w")

        Label(form, text="Disciplina:").grid(row=4, column=0, padx=5, pady=4, sticky="e")
        self.mapaDiscEd = carregarDisciplinas()
        self.edDisciplina = Combobox(form, values=list(self.mapaDiscEd), state="readonly",
                                     width=38)
        if self.mapaDiscEd:
            self.edDisciplina.current(0)
        self.edDisciplina.grid(row=4, column=1, padx=5, pady=4, sticky="w")

        self.btnSalvarEdicao = Button(form, text="Salvar alterações", width=20,
                                      command=self.salvarEdicao)
        self.btnSalvarEdicao.grid(row=5, column=0, columnspan=2, pady=10)

# =======================================
# LISTA COM SCROLLBAR (ordenada: Alta > Média > Baixa)
# =======================================
        quadroLista = Frame(self.janelaEditar)
        quadroLista.grid(row=2, column=0, sticky="nsew", padx=10, pady=(0, 10))
        quadroLista.columnconfigure(0, weight=1)
        quadroLista.rowconfigure(0, weight=1)

        self.listaEd = Treeview(
            quadroLista,
            columns=("titulo", "descricao", "prazo", "prioridade", "disciplina"),
            show="headings",
            selectmode="browse"
        )
        self.listaEd.heading("titulo", text="Título")
        self.listaEd.heading("descricao", text="Descrição")
        self.listaEd.heading("prazo", text="Prazo")
        self.listaEd.heading("prioridade", text="Prioridade")
        self.listaEd.heading("disciplina", text="Disciplina")
        self.listaEd.column("titulo", width=140)
        self.listaEd.column("descricao", width=170)
        self.listaEd.column("prazo", width=85, anchor="center")
        self.listaEd.column("prioridade", width=85, anchor="center")
        self.listaEd.column("disciplina", width=190)
        self.listaEd.grid(row=0, column=0, sticky="nsew")

        for prioridade, cor in CORES.items():
            self.listaEd.tag_configure(prioridade, foreground=cor)

        scroll = Scrollbar(quadroLista, orient="vertical", command=self.listaEd.yview)
        scroll.grid(row=0, column=1, sticky="ns")
        self.listaEd.configure(yscrollcommand=scroll.set)

        # Ao clicar em uma tarefa, os campos de edição são preenchidos
        self.listaEd.bind("<<TreeviewSelect>>", self.selecionarTarefaEdicao)

        self.carregarTarefasEdicao()
        
# =======================================
# CARREGAR TAREFAS
# =======================================
    def carregarTarefasEdicao(self, selecionar=None):
        # Limpa a lista e o calendário antes de recarregar
        self.listaEd.delete(*self.listaEd.get_children())
        self.calendarioEd.calevent_remove("all")
        self.tarefasEd = {}

        conexao = conectar()
        try:
            tarefas = conexao.execute(
                "SELECT t.id_tarefa, t.titulo_tarefa, t.descricao, t.prazo, "
                "t.prioridade, d.descricao "
                "FROM tarefa t JOIN disciplina d ON d.id_disciplina = t.id_disciplina "
                "WHERE t.id_aluno = ? "
                f"ORDER BY {ORDEM_PRIORIDADE}, t.prazo",
                (self.idAluno,)
            ).fetchall()
        finally:
            conexao.close()

        for id_tarefa, titulo, descricao, prazo, prioridade, disciplina in tarefas:
            data = datetime.strptime(prazo, "%Y-%m-%d")
            descricao = descricao or ""
            self.tarefasEd[str(id_tarefa)] = (titulo, descricao, data, prioridade, disciplina)

            # O id da tarefa é usado como identificador da linha (iid)
            self.listaEd.insert(
                "", END, iid=str(id_tarefa),
                values=(titulo, descricao, data.strftime("%d/%m/%Y"),
                        prioridade, disciplina),
                tags=(prioridade,)
            )

            # Data pintada no calendário
            self.calendarioEd.calevent_create(data.date(), titulo, tags=prioridade)

        # Reseleciona a tarefa que acabou de ser editada
        if selecionar is not None and str(selecionar) in self.tarefasEd:
            self.listaEd.selection_set(str(selecionar))
            self.listaEd.see(str(selecionar))

# =======================================
# SELECIONAR TAREFA EDIÇÃO
# =======================================
    def selecionarTarefaEdicao(self, evento=None):
        selecao = self.listaEd.selection()
        if not selecao:
            return

        iid = selecao[0]
        titulo, descricao, data, prioridade, disciplina = self.tarefasEd[iid]
        self.idEditando = int(iid)

        # Preenche os campos com os dados atuais da tarefa
        self.edTitulo.delete(0, END)
        self.edTitulo.insert(0, titulo)

        self.edDescricao.delete(0, END)
        self.edDescricao.insert(0, descricao)

        self.edPrazo.set_date(data.date())
        self.edPrioridade.set(prioridade)
        self.edDisciplina.set(disciplina)

        # Leva o calendário até o mês do prazo da tarefa
        self.calendarioEd.see(data.date())
        
# =======================================
# SALVAR EDIÇÃO
# ======================================= 
    def salvarEdicao(self):
        try:
            if self.idEditando is None:
                raise ValueError("Selecione uma tarefa na lista para editar.")

            titulo = self.edTitulo.get().strip()
            descricao = self.edDescricao.get().strip()
            prioridade = self.edPrioridade.get()
            disciplina = self.edDisciplina.get()

            if not titulo:
                raise ValueError("Informe o título da tarefa.")

            if len(titulo) > 100:
                raise ValueError("O título pode ter no máximo 100 caracteres.")

            if len(descricao) > 255:
                raise ValueError("A descrição pode ter no máximo 255 caracteres.")

            if disciplina not in self.mapaDiscEd:
                raise ValueError("Selecione a disciplina.")

            prazo = datetime.strptime(self.edPrazo.get(), "%d/%m/%Y").strftime("%Y-%m-%d")

            conexao = conectar()
            try:
                # id_aluno no WHERE garante que só tarefas do próprio usuário são alteradas
                conexao.execute(
                    "UPDATE tarefa "
                    "SET titulo_tarefa = ?, descricao = ?, prazo = ?, "
                    "    prioridade = ?, id_disciplina = ? "
                    "WHERE id_tarefa = ? AND id_aluno = ?",
                    (titulo, descricao, prazo, prioridade,
                     self.mapaDiscEd[disciplina], self.idEditando, self.idAluno)
                )
                conexao.commit()
            finally:
                conexao.close()

            showinfo("Tarefa", "Tarefa atualizada com sucesso!",
                     parent=self.janelaEditar)

            # Recarrega lista e calendário (a ordem por prioridade é refeita)
            self.carregarTarefasEdicao(selecionar=self.idEditando)

        except ValueError as erro:
            showerror("Dados inválidos", str(erro), parent=self.janelaEditar)
        except sqlite3.Error as erro:
            showerror("Erro no banco de dados", str(erro), parent=self.janelaEditar)

# *=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=
# JANELA MARCAR COMO CONCLUIDA

    def MarcarConcluida(self):
        if self._jaAberta("janelaConcluir"):
            return

        self.janelaConcluir = Toplevel(self)
        self.janelaConcluir.title("MARCAR COMO CONCLUÍDA")
        self.janelaConcluir.geometry("780x450")

        self.janelaConcluir.columnconfigure(0, weight=1)
        self.janelaConcluir.rowconfigure(0, weight=1)  # a lista ocupa o espaço que sobra
        
# =======================================
# LISTA COM SCROLLBAR 
# =======================================

        quadroLista = Frame(self.janelaConcluir)
        quadroLista.grid(row=0, column=0, sticky="nsew", padx=10, pady=10)
        quadroLista.columnconfigure(0, weight=1)
        quadroLista.rowconfigure(0, weight=1)

        self.listaConc = Treeview(
            quadroLista,
            columns=("titulo", "descricao", "prazo", "prioridade", "disciplina", "status"),
            show="headings",
            selectmode="browse"
        )
        self.listaConc.heading("titulo", text="Título")
        self.listaConc.heading("descricao", text="Descrição")
        self.listaConc.heading("prazo", text="Prazo")
        self.listaConc.heading("prioridade", text="Prioridade")
        self.listaConc.heading("disciplina", text="Disciplina")
        self.listaConc.heading("status", text="Status")
        self.listaConc.column("titulo", width=130)
        self.listaConc.column("descricao", width=150)
        self.listaConc.column("prazo", width=80, anchor="center")
        self.listaConc.column("prioridade", width=80, anchor="center")
        self.listaConc.column("disciplina", width=200)
        self.listaConc.column("status", width=80, anchor="center")
        self.listaConc.grid(row=0, column=0, sticky="nsew")

        # Tarefas pendentes na cor da prioridade, concluídas em cinza
        for prioridade, cor in CORES.items():
            self.listaConc.tag_configure(prioridade, foreground=cor)
        self.listaConc.tag_configure(NOME_STATUS[STATUS_CONCLUIDA], foreground="gray")

        scroll = Scrollbar(quadroLista, orient="vertical", command=self.listaConc.yview)
        scroll.grid(row=0, column=1, sticky="ns")
        self.listaConc.configure(yscrollcommand=scroll.set)

        # Mostra ou esconde o botão conforme haja uma tarefa selecionada
        self.listaConc.bind("<<TreeviewSelect>>", self.aoSelecionarConcluir)

        # BOTÕES (lado a lado, embaixo da lista)
        botoes = Frame(self.janelaConcluir)
        botoes.grid(row=1, column=0, pady=(0, 15))
        botoes.columnconfigure(0, minsize=200)   # reserva o lugar do botão que começa escondido

        # Marcar como concluída: começa escondido; aparece ao selecionar uma tarefa
        self.btnConcluir = Button(botoes, text="Marcar como concluída",
                                  width=25, command=self.concluirTarefa)
        self.btnConcluir.grid(row=0, column=0, padx=5)
        self.btnConcluir.grid_remove()

        # Remover tarefa: sempre visível (se nada estiver selecionado, avisa)
        self.btnRemoverTarefa = Button(botoes, text="Remover tarefa", width=18,
                                       command=self.removerTarefa)
        self.btnRemoverTarefa.grid(row=0, column=1, padx=5)

        self.carregarTarefasConcluir()

# =======================================
# CARREGAR TAREFAS CONCLUIR
# =======================================
    def carregarTarefasConcluir(self):
        self.listaConc.delete(*self.listaConc.get_children())

        conexao = conectar()
        try:
            tarefas = conexao.execute(
                "SELECT t.id_tarefa, t.titulo_tarefa, t.descricao, t.prazo, "
                "t.prioridade, d.descricao, t.status "
                "FROM tarefa t JOIN disciplina d ON d.id_disciplina = t.id_disciplina "
                "WHERE t.id_aluno = ? "
                f"ORDER BY t.status, {ORDEM_PRIORIDADE}, t.prazo",
                (self.idAluno,)
            ).fetchall()
        finally:
            conexao.close()

        for id_tarefa, titulo, descricao, prazo, prioridade, disciplina, status in tarefas:
            data = datetime.strptime(prazo, "%Y-%m-%d")
            tag = NOME_STATUS[STATUS_CONCLUIDA] if status == STATUS_CONCLUIDA else prioridade

            # O id da tarefa é usado como identificador da linha (iid)
            self.listaConc.insert(
                "", END, iid=str(id_tarefa),
                values=(titulo, descricao or "", data.strftime("%d/%m/%Y"),
                        prioridade, disciplina, NOME_STATUS[status]),
                tags=(tag,)
            )

    def aoSelecionarConcluir(self, evento=None):
        if self.listaConc.selection():
            self.btnConcluir.grid()          # mostra o botão
        else:
            self.btnConcluir.grid_remove()   # esconde o botão

    def concluirTarefa(self):
        selecao = self.listaConc.selection()

        try:
            if not selecao:
                raise ValueError("Selecione uma tarefa para marcar como concluída.")

            iid = selecao[0]
            if self.listaConc.set(iid, "status") == NOME_STATUS[STATUS_CONCLUIDA]:
                raise ValueError("Esta tarefa já está concluída.")

            conexao = conectar()
            try:
                conexao.execute(
                    "UPDATE tarefa SET status = ? WHERE id_tarefa = ? AND id_aluno = ?",
                    (STATUS_CONCLUIDA, int(iid), self.idAluno)
                )
                conexao.commit()
            finally:
                conexao.close()

            showinfo("Tarefa", "Tarefa marcada como concluída!",
                     parent=self.janelaConcluir)

            # Recarrega a lista (a seleção some e o botão é escondido de novo)
            self.carregarTarefasConcluir()
            self.btnConcluir.grid_remove()

        except ValueError as erro:
            showerror("Atenção", str(erro), parent=self.janelaConcluir)
        except sqlite3.Error as erro:
            showerror("Erro no banco de dados", str(erro), parent=self.janelaConcluir)

# =======================================
# REMOVER TAREFA
# =======================================    
    def removerTarefa(self):
        selecao = self.listaConc.selection()

        try:
            if not selecao:
                raise ValueError("Selecione uma tarefa para remover.")

            iid = selecao[0]
            titulo = self.listaConc.set(iid, "titulo")

            if not askyesno("Remover tarefa",
                            f'Deseja realmente remover a tarefa "{titulo}"?',
                            parent=self.janelaConcluir):
                return

            conexao = conectar()
            try:
                # id_aluno no WHERE garante que só tarefas do próprio usuário são removidas
                cursor = conexao.execute(
                    "DELETE FROM tarefa WHERE id_tarefa = ? AND id_aluno = ?",
                    (int(iid), self.idAluno)
                )
                conexao.commit()
                removidas = cursor.rowcount
            finally:
                conexao.close()

            if removidas == 0:
                raise ValueError("Tarefa não encontrada.")

            showinfo("Tarefa", "Tarefa removida com sucesso!",
                     parent=self.janelaConcluir)

            # Recarrega esta lista (a seleção some, então o botão de concluir se esconde)
            self.carregarTarefasConcluir()
            self.btnConcluir.grid_remove()

            # Se a tarefa removida estava aberta para edição, solta ela
            if getattr(self, "idEditando", None) == int(iid):
                self.idEditando = None

            # Mantém as outras janelas de tarefas, se abertas, em dia
            for nome, atualizar in (("janelaListar", self.carregarTarefas),
                                    ("janelaEditar", self.carregarTarefasEdicao)):
                janela = getattr(self, nome, None)
                if janela is not None and janela.winfo_exists():
                    atualizar()

        except ValueError as erro:
            showerror("Atenção", str(erro), parent=self.janelaConcluir)
        except sqlite3.Error as erro:
            showerror("Erro no banco de dados", str(erro), parent=self.janelaConcluir)

# *=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=
# JANELA DE RESUMO (com abas: Resumo, Criar Flash Card, Responder Flash Cards)

    def Resumo(self):
        if self._jaAberta("janelaResumo"):
            return

        self.janelaResumo = Toplevel(self)
        self.janelaResumo.title("RESUMO E FLASH CARDS")
        # A altura se adapta à tela (descontando a barra de tarefas), para os botões
        # nunca ficarem fora da área visível. A janela abre perto do topo.
        altura = min(700, self.janelaResumo.winfo_screenheight() - 120)
        self.janelaResumo.geometry(f"780x{altura}+80+10")
        self.janelaResumo.minsize(700, 450)

        self.janelaResumo.columnconfigure(0, weight=1)
        self.janelaResumo.rowconfigure(0, weight=1)

        # Disciplinas (da tabela disciplina), usadas nas três abas
        self.mapaDiscRes = carregarDisciplinas()

        abas = Notebook(self.janelaResumo)
        abas.grid(row=0, column=0, sticky="nsew", padx=10, pady=10)

        self.abaResumo = Frame(abas)
        self.abaCriarFlash = Frame(abas)
        self.abaResponder = Frame(abas)

        abas.add(self.abaResumo, text="Resumo")
        abas.add(self.abaCriarFlash, text="Criar Flash Card")
        abas.add(self.abaResponder, text="Responder Flash Cards")

        self._montarAbaResumo()
        self._montarAbaCriarFlash()
        self._montarAbaResponder()
        

# =======================================
# ABA 1: RESUMO
# =======================================
    
    def _montarAbaResumo(self):
        aba = self.abaResumo
        aba.columnconfigure(1, weight=1)
        aba.rowconfigure(2, weight=1)   # a área de texto ocupa o espaço que sobra

        # TÍTULO
        Label(aba, text="Título:").grid(row=0, column=0, padx=5, pady=5, sticky="e")
        self.resTitulo = Entry(aba)
        self.resTitulo.grid(row=0, column=1, padx=5, pady=5, sticky="ew")

        # DISCIPLINA
        Label(aba, text="Disciplina:").grid(row=1, column=0, padx=5, pady=5, sticky="e")
        self.resDisciplina = Combobox(aba, values=list(self.mapaDiscRes),
                                      state="readonly", width=40)
        if self.mapaDiscRes:
            self.resDisciplina.current(0)
        self.resDisciplina.grid(row=1, column=1, padx=5, pady=5, sticky="w")

        # CONTEÚDO (área de texto com scrollbar)
        Label(aba, text="Conteúdo:").grid(row=2, column=0, padx=5, pady=5, sticky="ne")
        quadroTexto = Frame(aba)
        quadroTexto.grid(row=2, column=1, padx=5, pady=5, sticky="nsew")
        quadroTexto.columnconfigure(0, weight=1)
        quadroTexto.rowconfigure(0, weight=1)

        self.resConteudo = Text(quadroTexto, wrap="word", height=8)
        self.resConteudo.grid(row=0, column=0, sticky="nsew")

        barra = Scrollbar(quadroTexto, orient="vertical", command=self.resConteudo.yview)
        barra.grid(row=0, column=1, sticky="ns")
        self.resConteudo.configure(yscrollcommand=barra.set)

        # BOTÕES
        botoes = Frame(aba)
        botoes.grid(row=3, column=0, columnspan=2, pady=10)

        Button(botoes, text="Salvar resumo", width=18,
               command=self.salvarResumo).grid(row=0, column=0, padx=5)
        Button(botoes, text="Salvar em .txt", width=18,
               command=self.salvarResumoTxt).grid(row=0, column=1, padx=5)
        Button(botoes, text="Limpar", width=12,
               command=self.limparResumo).grid(row=0, column=2, padx=5)

# =======================================
# LER RESUMO
# =======================================    
    def _lerResumo(self):
        """Lê e valida os campos do resumo. Devolve (título, disciplina, conteúdo)."""
        titulo = self.resTitulo.get().strip()
        disciplina = self.resDisciplina.get()
        conteudo = self.resConteudo.get("1.0", "end-1c").strip()

        if not titulo:
            raise ValueError("Informe o título do resumo.")

        if len(titulo) > 100:
            raise ValueError("O título pode ter no máximo 100 caracteres.")

        if not conteudo:
            raise ValueError("Escreva o conteúdo do resumo.")

        return titulo, disciplina, conteudo
    
# =======================================
# SALVAR RESUMO
# =======================================
    def salvarResumo(self):
        try:
            titulo, disciplina, conteudo = self._lerResumo()

            if disciplina not in self.mapaDiscRes:
                raise ValueError("Selecione a disciplina.")

            # A coluna conteudo da tabela resumo é VARCHAR(2000)
            if len(conteudo) > 2000:
                raise ValueError(
                    f"O conteúdo pode ter no máximo 2000 caracteres "
                    f"(agora tem {len(conteudo)})."
                )

            conexao = conectar()
            try:
                conexao.execute(
                    "INSERT INTO resumo (titulo_resumo, conteudo, id_aluno, id_disciplina) "
                    "VALUES (?, ?, ?, ?)",
                    (titulo, conteudo, self.idAluno, self.mapaDiscRes[disciplina])
                )
                conexao.commit()
            finally:
                conexao.close()

            showinfo("Resumo",
                     "Resumo salvo! Agora você pode criar flash cards a partir dele.\n"
                     "Use \"Salvar em .txt\" para exportar ou \"Limpar\" para começar outro.",
                     parent=self.janelaResumo)

            # O novo resumo passa a aparecer na aba "Criar Flash Card".
            # A disciplina dessa aba é ajustada para a do resumo que acabou de ser
            # salvo, senão a lista de resumos ficaria filtrada por outra disciplina.
            self.flDisciplina.set(disciplina)
            self.atualizarResumosFlash()

        except ValueError as erro:
            showerror("Dados inválidos", str(erro), parent=self.janelaResumo)
        except sqlite3.Error as erro:
            showerror("Erro no banco de dados", str(erro), parent=self.janelaResumo)

# =======================================
# SALVAR RESUMO EM TXT
# =======================================
    def salvarResumoTxt(self):
        try:
            titulo, disciplina, conteudo = self._lerResumo()

            # Sugere o título como nome do arquivo (sem caracteres proibidos no Windows)
            invalidos = '\\/:*?"<>|'
            sugestao = "".join(c for c in titulo if c not in invalidos).strip() or "resumo"

            caminho = filedialog.asksaveasfilename(
                parent=self.janelaResumo,
                title="Salvar resumo em arquivo de texto",
                defaultextension=".txt",
                initialfile=sugestao,
                filetypes=[("Arquivo de texto", "*.txt")]
            )
            if not caminho:   # o usuário cancelou
                return

            with open(caminho, "w", encoding="utf-8") as arquivo:
                arquivo.write(f"Título: {titulo}\n")
                if disciplina:
                    arquivo.write(f"Disciplina: {disciplina}\n")
                arquivo.write(f"Autor: {self.usuarioLogado}\n")
                arquivo.write(f"Data: {datetime.now():%d/%m/%Y}\n\n")
                arquivo.write(conteudo + "\n")

            showinfo("Resumo", "Resumo salvo em arquivo de texto!",
                     parent=self.janelaResumo)

        except ValueError as erro:
            showerror("Dados inválidos", str(erro), parent=self.janelaResumo)
        except OSError as erro:
            showerror("Erro ao salvar o arquivo", str(erro), parent=self.janelaResumo)

# =======================================
# LIMPAR RESUMO
# =======================================

    def limparResumo(self):
        self.resTitulo.delete(0, END)
        self.resConteudo.delete("1.0", END)

# =======================================
# ABA 2: CRIAR FLASH CARD
# =======================================
    def _montarAbaCriarFlash(self):
        aba = self.abaCriarFlash
        aba.columnconfigure(0, weight=1)
        aba.rowconfigure(0, weight=1)

        caixa = Frame(aba)
        caixa.grid(row=0, column=0)

        # Resumos do aluno na disciplina escolhida: {texto mostrado: id_resumo}
        self.mapaResumosFl = {}

        fonte = Font(family="Times New Roman", size=16, slant="italic")
        Label(caixa, text="Criar Flash Card (verdadeiro ou falso)", font=fonte,
              fg="blue", bg="lightgray").grid(row=0, column=0, columnspan=2,
                                               padx=5, pady=(0, 15))
        
# =======================================
# DISCIPLINA
# =======================================
        Label(caixa, text="Disciplina:").grid(row=1, column=0, padx=5, pady=5, sticky="e")
        self.flDisciplina = Combobox(caixa, values=list(self.mapaDiscRes),
                                     state="readonly", width=40)
        if self.mapaDiscRes:
            self.flDisciplina.current(0)
        self.flDisciplina.grid(row=1, column=1, padx=5, pady=5, sticky="w")
        self.flDisciplina.bind("<<ComboboxSelected>>", self.atualizarResumosFlash)

# =======================================
# RESUMO (o flash card pertence a um resumo seu)
# =======================================
        Label(caixa, text="Resumo:").grid(row=2, column=0, padx=5, pady=5, sticky="e")
        self.flResumo = Combobox(caixa, values=[], state="readonly", width=40)
        self.flResumo.grid(row=2, column=1, padx=5, pady=5, sticky="w")

# =======================================
# PERGUNTA
# =======================================
        Label(caixa, text="Pergunta:").grid(row=3, column=0, padx=5, pady=5, sticky="e")
        self.flPergunta = Entry(caixa, width=43)
        self.flPergunta.grid(row=3, column=1, padx=5, pady=5, sticky="w")

# =======================================
# RESPOSTA CORRETA (verdadeiro ou falso)
# =======================================
        Label(caixa, text="Resposta correta:").grid(row=4, column=0, padx=5, pady=5, sticky="e")
        quadroResposta = Frame(caixa)
        quadroResposta.grid(row=4, column=1, padx=5, pady=5, sticky="w")
        self.flResposta = StringVar(self.janelaResumo, value="")
        Radiobutton(quadroResposta, text="Verdadeiro", variable=self.flResposta,
                    value="Verdadeiro").grid(row=0, column=0, padx=(0, 15))
        Radiobutton(quadroResposta, text="Falso", variable=self.flResposta,
                    value="Falso").grid(row=0, column=1)
        
# =======================================
# BOTÕES CRIAR FLASH CARD E REMOVER RESUMO
# =======================================
        botoesFlash = Frame(caixa)
        botoesFlash.grid(row=5, column=0, columnspan=2, pady=20)

        Button(botoesFlash, text="Criar Flash Card", width=20,
               command=self.criarFlashCard).grid(row=0, column=0, padx=5)

        # Remove o resumo escolhido no campo "Resumo" (e os flash cards dele)
        Button(botoesFlash, text="Remover resumo", width=20,
               command=self.removerResumo).grid(row=0, column=1, padx=5)

        self.atualizarResumosFlash()
        
# =======================================
# ATUALIZAR RESUMO FLASH
# =======================================
    def atualizarResumosFlash(self, evento=None):
        """Preenche o campo Resumo com os resumos do aluno na disciplina escolhida."""
        disciplina = self.flDisciplina.get()
        self.mapaResumosFl = {}

        if disciplina in self.mapaDiscRes:
            conexao = conectar()
            try:
                linhas = conexao.execute(
                    "SELECT id_resumo, titulo_resumo FROM resumo "
                    "WHERE id_aluno = ? AND id_disciplina = ? ORDER BY titulo_resumo",
                    (self.idAluno, self.mapaDiscRes[disciplina])
                ).fetchall()
            except sqlite3.Error as erro:
                showerror("Erro no banco de dados", str(erro), parent=self.janelaResumo)
                linhas = []
            finally:
                conexao.close()

            self.mapaResumosFl = {
                f"{id_resumo} - {titulo}": id_resumo for id_resumo, titulo in linhas
            }

        self.flResumo["values"] = list(self.mapaResumosFl)
        if self.mapaResumosFl:
            self.flResumo.current(0)
        else:
            self.flResumo.set("")
            
# =======================================
# CRIAR FLASH CARD
# =======================================
    def criarFlashCard(self):
        pergunta = self.flPergunta.get().strip()
        resposta = self.flResposta.get()
        resumo = self.flResumo.get()

        try:
            if resumo not in self.mapaResumosFl:
                raise ValueError(
                    "Você ainda não tem resumo nessa disciplina.\n"
                    "Salve um resumo na aba \"Resumo\" antes de criar o flash card."
                )

            if not pergunta:
                raise ValueError("Escreva a pergunta.")

            if len(pergunta) > 255:
                raise ValueError("A pergunta pode ter no máximo 255 caracteres.")

            if resposta not in ("Verdadeiro", "Falso"):
                raise ValueError("Escolha a resposta correta: Verdadeiro ou Falso.")

            conexao = conectar()
            try:
                conexao.execute(
                    "INSERT INTO flashcard (pergunta, resposta, id_resumo) VALUES (?, ?, ?)",
                    (pergunta, resposta, self.mapaResumosFl[resumo])
                )
                conexao.commit()
            finally:
                conexao.close()

            showinfo("Flash Card", "Flash card criado com sucesso!",
                     parent=self.janelaResumo)

            self.flPergunta.delete(0, END)
            self.flResposta.set("")

            # O novo flash card já aparece na aba de responder
            self.carregarFlashCards()

        except ValueError as erro:
            showerror("Dados inválidos", str(erro), parent=self.janelaResumo)
        except sqlite3.Error as erro:
            showerror("Erro no banco de dados", str(erro), parent=self.janelaResumo)

# =======================================
# REMOVER RESUMO
# =======================================
    def removerResumo(self):
        resumo = self.flResumo.get()

        try:
            if resumo not in self.mapaResumosFl:
                raise ValueError("Selecione um resumo para remover.")

            idResumo = self.mapaResumosFl[resumo]

            # Conta os flash cards do resumo, para avisar antes de apagar
            conexao = conectar()
            try:
                qtdFlash = conexao.execute(
                    "SELECT COUNT(*) FROM flashcard WHERE id_resumo = ?",
                    (idResumo,)
                ).fetchone()[0]
            finally:
                conexao.close()

            aviso = f'Deseja realmente remover o resumo "{resumo}"?'
            if qtdFlash > 0:
                aviso += (f"\n\nOs {qtdFlash} flash card(s) criados a partir dele "
                          f"também serão removidos.")

            if not askyesno("Remover resumo", aviso, parent=self.janelaResumo):
                return

            conexao = conectar()
            try:
                # id_aluno no WHERE garante que só resumos do próprio usuário são removidos.
                # Os flash cards do resumo saem junto (ON DELETE CASCADE no banco).
                cursor = conexao.execute(
                    "DELETE FROM resumo WHERE id_resumo = ? AND id_aluno = ?",
                    (idResumo, self.idAluno)
                )
                conexao.commit()
                removidos = cursor.rowcount
            finally:
                conexao.close()

            if removidos == 0:
                raise ValueError("Resumo não encontrado.")

            showinfo("Resumo", "Resumo removido com sucesso!",
                     parent=self.janelaResumo)

            # Atualiza o campo Resumo desta aba e a lista da aba "Responder Flash Cards"
            self.atualizarResumosFlash()
            self.carregarFlashCards()

        except ValueError as erro:
            showerror("Atenção", str(erro), parent=self.janelaResumo)
        except sqlite3.Error as erro:
            showerror("Erro no banco de dados", str(erro), parent=self.janelaResumo)

# =======================================
# ABA 3: RESPONDER FLASH CARDS (de todos os usuários)
# =======================================
    def _montarAbaResponder(self):
        aba = self.abaResponder
        aba.columnconfigure(0, weight=1)
        aba.rowconfigure(1, weight=1)   # a lista ocupa o espaço que sobra
        aba.rowconfigure(2, weight=2)   # a área do conteúdo do resumo recebe mais espaço

        # Dono de cada flash card listado: {id_flashcard: id_aluno}
        self.donosFlash = {}

        # FILTRO POR DISCIPLINA
        filtro = Frame(aba)
        filtro.grid(row=0, column=0, pady=5)

        Label(filtro, text="Disciplina:").grid(row=0, column=0, padx=5)
        self.filtroFlash = Combobox(filtro, values=("Todas",) + tuple(self.mapaDiscRes),
                                    state="readonly", width=40)
        self.filtroFlash.current(0)
        self.filtroFlash.grid(row=0, column=1, padx=5)
        self.filtroFlash.bind("<<ComboboxSelected>>", self.carregarFlashCards)

        # LISTA COM SCROLLBAR (a resposta correta NÃO aparece aqui)
        quadroLista = Frame(aba)
        quadroLista.grid(row=1, column=0, sticky="nsew", padx=5, pady=5)
        quadroLista.columnconfigure(0, weight=1)
        quadroLista.rowconfigure(0, weight=1)

        self.listaFlash = Treeview(
            quadroLista,
            columns=("disciplina", "pergunta", "autor"),
            show="headings",
            selectmode="browse",
            height=4
        )
        self.listaFlash.heading("disciplina", text="Disciplina")
        self.listaFlash.heading("pergunta", text="Pergunta")
        self.listaFlash.heading("autor", text="Criado por")
        self.listaFlash.column("disciplina", width=230)
        self.listaFlash.column("pergunta", width=300)
        self.listaFlash.column("autor", width=130)
        self.listaFlash.grid(row=0, column=0, sticky="nsew")

        scroll = Scrollbar(quadroLista, orient="vertical", command=self.listaFlash.yview)
        scroll.grid(row=0, column=1, sticky="ns")
        self.listaFlash.configure(yscrollcommand=scroll.set)

        self.listaFlash.bind("<<TreeviewSelect>>", self.aoSelecionarFlash)

        # CONTEÚDO DO RESUMO (somente leitura): mostra o resumo ao qual o flash card pertence
        quadroConteudo = Frame(aba)
        quadroConteudo.grid(row=2, column=0, sticky="nsew", padx=5, pady=5)
        quadroConteudo.columnconfigure(0, weight=1)
        quadroConteudo.rowconfigure(1, weight=1)

        self.lblTituloResumoFlash = Label(quadroConteudo, text="Conteúdo do resumo:",
                                          font=("Verdana", 10, "bold"), anchor="w")
        self.lblTituloResumoFlash.grid(row=0, column=0, columnspan=2, sticky="ew")

        self.txtConteudoFlash = Text(quadroConteudo, wrap="word", height=6, state="disabled")
        self.txtConteudoFlash.grid(row=1, column=0, sticky="nsew")

        barraConteudo = Scrollbar(quadroConteudo, orient="vertical",
                                  command=self.txtConteudoFlash.yview)
        barraConteudo.grid(row=1, column=1, sticky="ns")
        self.txtConteudoFlash.configure(yscrollcommand=barraConteudo.set)

        # PAINEL: pergunta completa + botões de resposta
        painel = Frame(aba)
        painel.grid(row=3, column=0, pady=10)

        self.lblPerguntaFlash = Label(painel, text="Selecione um flash card na lista.",
                                      wraplength=650, justify="center",
                                      font=("Verdana", 11))
        self.lblPerguntaFlash.grid(row=0, column=0, columnspan=3, pady=10)

        self.btnVerdadeiro = Button(painel, text="Verdadeiro", width=15,
                                    command=lambda: self.responderFlash("Verdadeiro"))
        self.btnVerdadeiro.grid(row=1, column=0, padx=5)

        self.btnFalso = Button(painel, text="Falso", width=15,
                               command=lambda: self.responderFlash("Falso"))
        self.btnFalso.grid(row=1, column=1, padx=5)

        # Só aparece para quem criou o flash card selecionado
        self.btnRemoverFlash = Button(painel, text="Remover flash card", width=18,
                                      command=self.removerFlash)
        self.btnRemoverFlash.grid(row=1, column=2, padx=(25, 5))
        self.btnRemoverFlash.grid_remove()

        self.carregarFlashCards()
        
# =======================================
# CARREGAR FLASH CARDS
# =======================================
    def carregarFlashCards(self, evento=None):
        escolhida = self.filtroFlash.get()

        self.listaFlash.delete(*self.listaFlash.get_children())
        self.donosFlash = {}

        sql = ("SELECT f.id_flashcard, d.descricao, f.pergunta, a.usuario, a.id_aluno "
               "FROM flashcard f "
               "JOIN resumo r     ON r.id_resumo = f.id_resumo "
               "JOIN disciplina d ON d.id_disciplina = r.id_disciplina "
               "JOIN aluno a      ON a.id_aluno = r.id_aluno")
        parametros = []

        if escolhida in self.mapaDiscRes:   # "Todas" não está no mapa
            sql += " WHERE r.id_disciplina = ?"
            parametros.append(self.mapaDiscRes[escolhida])

        sql += " ORDER BY d.descricao, f.id_flashcard"

        conexao = conectar()
        try:
            linhas = conexao.execute(sql, parametros).fetchall()
        except sqlite3.Error as erro:
            showerror("Erro no banco de dados", str(erro), parent=self.janelaResumo)
            linhas = []
        finally:
            conexao.close()

        for id_flash, disciplina, pergunta, autor, id_autor in linhas:
            self.donosFlash[str(id_flash)] = id_autor
            nome_autor = f"{autor} (você)" if id_autor == self.idAluno else autor

            # O id do flash card é usado como identificador da linha (iid)
            self.listaFlash.insert(
                "", END, iid=str(id_flash),
                values=(disciplina, pergunta, nome_autor)
            )

        self.aoSelecionarFlash()

# =======================================
# MOSTRAR CONTEÚDO DO RESUMO (somente leitura)
# =======================================
    def _mostrarConteudoFlash(self, titulo, conteudo):
        """Escreve o título e o conteúdo do resumo na área de texto da aba Responder."""
        self.lblTituloResumoFlash["text"] = titulo
        self.txtConteudoFlash.config(state="normal")   # precisa estar liberado para escrever
        self.txtConteudoFlash.delete("1.0", END)
        self.txtConteudoFlash.insert("1.0", conteudo)
        self.txtConteudoFlash.config(state="disabled") # volta a ser somente leitura
        
# =======================================
# SELECIONAR FLASH CARD
# =======================================
    def aoSelecionarFlash(self, evento=None):
        selecao = self.listaFlash.selection()

        if not selecao:
            self.lblPerguntaFlash["text"] = "Selecione um flash card na lista."
            self._mostrarConteudoFlash("Conteúdo do resumo:", "")
            self.btnRemoverFlash.grid_remove()
            return

        iid = selecao[0]
        self.lblPerguntaFlash["text"] = self.listaFlash.set(iid, "pergunta")

        # Busca o resumo ao qual o flash card pertence (a resposta correta NÃO é buscada aqui)
        conexao = conectar()
        try:
            linha = conexao.execute(
                "SELECT r.titulo_resumo, r.conteudo "
                "FROM flashcard f JOIN resumo r ON r.id_resumo = f.id_resumo "
                "WHERE f.id_flashcard = ?",
                (int(iid),)
            ).fetchone()
        except sqlite3.Error as erro:
            showerror("Erro no banco de dados", str(erro), parent=self.janelaResumo)
            linha = None
        finally:
            conexao.close()

        if linha is not None:
            self._mostrarConteudoFlash(f"Resumo: {linha[0]}", linha[1])
        else:
            self._mostrarConteudoFlash("Conteúdo do resumo:", "")

        # O botão de remover só aparece para o criador do flash card
        if self.donosFlash.get(iid) == self.idAluno:
            self.btnRemoverFlash.grid()
        else:
            self.btnRemoverFlash.grid_remove()

    def responderFlash(self, escolha):
        selecao = self.listaFlash.selection()

        try:
            if not selecao:
                raise ValueError("Selecione um flash card para responder.")

            # A resposta correta só é buscada no banco na hora de conferir
            conexao = conectar()
            try:
                linha = conexao.execute(
                    "SELECT resposta FROM flashcard WHERE id_flashcard = ?",
                    (int(selecao[0]),)
                ).fetchone()
            finally:
                conexao.close()

            if linha is None:
                self.carregarFlashCards()
                raise ValueError("Este flash card não existe mais.")

            correta = linha[0]

            if escolha == correta:
                showinfo("Resultado", "Você acertou!", parent=self.janelaResumo)
            else:
                showinfo("Resultado",
                         f"Você errou. A resposta correta é: {correta}.",
                         parent=self.janelaResumo)

        except ValueError as erro:
            showerror("Atenção", str(erro), parent=self.janelaResumo)
        except sqlite3.Error as erro:
            showerror("Erro no banco de dados", str(erro), parent=self.janelaResumo)
            
# =======================================
# REMOVER FLASH CARD
# =======================================
    def removerFlash(self):
        selecao = self.listaFlash.selection()

        try:
            if not selecao:
                raise ValueError("Selecione um flash card para remover.")

            iid = selecao[0]
            if self.donosFlash.get(iid) != self.idAluno:
                raise ValueError("Só quem criou o flash card pode removê-lo.")

            if not askyesno("Remover flash card",
                            "Deseja realmente remover este flash card?",
                            parent=self.janelaResumo):
                return

            conexao = conectar()
            try:
                # A subconsulta garante, no banco, que só o dono do resumo remove
                cursor = conexao.execute(
                    "DELETE FROM flashcard WHERE id_flashcard = ? "
                    "AND id_resumo IN (SELECT id_resumo FROM resumo WHERE id_aluno = ?)",
                    (int(iid), self.idAluno)
                )
                conexao.commit()
                removidos = cursor.rowcount
            finally:
                conexao.close()

            if removidos == 0:
                raise ValueError("Não foi possível remover: só quem criou o flash card pode removê-lo.")

            showinfo("Flash Card", "Flash card removido com sucesso!",
                     parent=self.janelaResumo)
            self.carregarFlashCards()

        except ValueError as erro:
            showerror("Atenção", str(erro), parent=self.janelaResumo)
        except sqlite3.Error as erro:
            showerror("Erro no banco de dados", str(erro), parent=self.janelaResumo)


# *=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=
# JANELA DE RELATÓRIO

    def gerarRelatorio(self):
        # Se já estiver aberta, fecha e gera de novo (assim os dados ficam atualizados)
        antiga = getattr(self, "janelaRelatorio", None)
        if antiga is not None and antiga.winfo_exists():
            antiga.destroy()

        try:
            relatorio = self._montarRelatorio()
        except sqlite3.Error as erro:
            showerror("Erro no banco de dados", str(erro), parent=self.janelaMenu)
            return

        self.janelaRelatorio = Toplevel(self)
        self.janelaRelatorio.title("RELATÓRIO DE PRODUTIVIDADE")
        self.janelaRelatorio.geometry("720x560")

        # O botão é empacotado primeiro (embaixo) para nunca ficar fora da janela
        Button(
            self.janelaRelatorio,
            text="Salvar relatório em TXT",
            width=25,
            command=lambda: self.salvarRelatorio(relatorio)
        ).pack(side=BOTTOM, pady=10)

        quadroTexto = Frame(self.janelaRelatorio)
        quadroTexto.pack(
            padx=10,
            pady=5,
            fill=BOTH,
            expand=True
        )

        # Fonte de largura fixa, para as colunas das tabelas ficarem alinhadas
        self.txtRelatorio = Text(
            quadroTexto,
            height=18,
            wrap=WORD,
            font=("Courier New", 10)
        )

        barra = Scrollbar(quadroTexto, orient="vertical", command=self.txtRelatorio.yview)
        self.txtRelatorio.configure(yscrollcommand=barra.set)

        barra.pack(side=RIGHT, fill=Y)
        self.txtRelatorio.pack(side=LEFT, fill=BOTH, expand=True)

        self.txtRelatorio.insert(END, relatorio)
        self.txtRelatorio.config(state=DISABLED)
        
# =======================================
# MONTAR RELATÓRIO
# =======================================
    def _montarRelatorio(self):
        """Monta o texto do relatório de produtividade do aluno logado."""
        hoje = datetime.now()
        hoje_iso = hoje.strftime("%Y-%m-%d")

        conexao = conectar()
        try:
            usuario, matricula = conexao.execute(
                "SELECT usuario, matricula FROM aluno WHERE id_aluno = ?",
                (self.idAluno,)
            ).fetchone()

            total, concluidas = conexao.execute(
                "SELECT COUNT(*), COALESCE(SUM(status), 0) FROM tarefa WHERE id_aluno = ?",
                (self.idAluno,)
            ).fetchone()

            por_prioridade = {
                prioridade: (qtd, conc)
                for prioridade, qtd, conc in conexao.execute(
                    "SELECT prioridade, COUNT(*), COALESCE(SUM(status), 0) "
                    "FROM tarefa WHERE id_aluno = ? GROUP BY prioridade",
                    (self.idAluno,)
                )
            }

            por_disciplina = conexao.execute(
                "SELECT d.descricao, COUNT(*), COALESCE(SUM(t.status), 0) "
                "FROM tarefa t JOIN disciplina d ON d.id_disciplina = t.id_disciplina "
                "WHERE t.id_aluno = ? "
                "GROUP BY d.id_disciplina, d.descricao "
                "ORDER BY COUNT(*) DESC, d.descricao",
                (self.idAluno,)
            ).fetchall()

            atrasadas = conexao.execute(
                "SELECT t.titulo_tarefa, t.prazo, t.prioridade, d.descricao "
                "FROM tarefa t JOIN disciplina d ON d.id_disciplina = t.id_disciplina "
                "WHERE t.id_aluno = ? AND t.status = 0 AND t.prazo < ? "
                "ORDER BY t.prazo",
                (self.idAluno, hoje_iso)
            ).fetchall()

            proximas = conexao.execute(
                "SELECT t.titulo_tarefa, t.prazo, t.prioridade, d.descricao "
                "FROM tarefa t JOIN disciplina d ON d.id_disciplina = t.id_disciplina "
                "WHERE t.id_aluno = ? AND t.status = 0 AND t.prazo >= ? "
                "ORDER BY t.prazo LIMIT 5",
                (self.idAluno, hoje_iso)
            ).fetchall()

            total_resumos = conexao.execute(
                "SELECT COUNT(*) FROM resumo WHERE id_aluno = ?",
                (self.idAluno,)
            ).fetchone()[0]

            total_flash = conexao.execute(
                "SELECT COUNT(*) FROM flashcard f "
                "JOIN resumo r ON r.id_resumo = f.id_resumo "
                "WHERE r.id_aluno = ?",
                (self.idAluno,)
            ).fetchone()[0]
        finally:
            conexao.close()
# *=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=
#
        def data_br(texto_iso):
            return datetime.strptime(texto_iso, "%Y-%m-%d").strftime("%d/%m/%Y")

        pendentes = total - concluidas
        percentual = f"{100 * concluidas / total:.1f}".replace(".", ",") if total else "0,0"

        grossa = "=" * 66
        fina = "-" * 66
        linhas = [
            "RELATÓRIO DE PRODUTIVIDADE",
            grossa,
            f"Aluno     : {usuario}",
            f"Matrícula : {matricula}",
            f"Gerado em : {hoje:%d/%m/%Y %H:%M}",
            grossa,
            "",
            "RESUMO GERAL",
            fina,
            f"  Total de tarefas    : {total}",
            f"  Concluídas          : {concluidas}",
            f"  Pendentes           : {pendentes}",
            f"  Percentual concluído: {percentual}%",
            "",
            "POR PRIORIDADE",
            fina,
            f"  {'Prioridade':<14}{'Total':>7}{'Concluídas':>13}{'Pendentes':>12}",
        ]

        # Da mais urgente para a menos urgente: Alta, Média, Baixa
        for prioridade in reversed(PRIORIDADES):
            qtd, conc = por_prioridade.get(prioridade, (0, 0))
            linhas.append(f"  {prioridade:<14}{qtd:>7}{conc:>13}{qtd - conc:>12}")

        linhas += [
            "",
            "POR DISCIPLINA",
            fina,
            f"  {'Disciplina':<40}{'Total':>7}{'Concl.':>8}{'Pend.':>8}",
        ]

        if por_disciplina:
            for disciplina, qtd, conc in por_disciplina:
                linhas.append(f"  {disciplina:<40}{qtd:>7}{conc:>8}{qtd - conc:>8}")
        else:
            linhas.append("  (nenhuma tarefa cadastrada)")

        linhas += ["", "TAREFAS ATRASADAS (pendentes com prazo vencido)", fina]

        if atrasadas:
            for titulo, prazo, prioridade, disciplina in atrasadas:
                dias = (hoje.date() - datetime.strptime(prazo, "%Y-%m-%d").date()).days
                linhas.append(f"  - {titulo} ({disciplina})")
                linhas.append(
                    f"      Prazo: {data_br(prazo)} | Prioridade: {prioridade} | "
                    f"{dias} dia(s) de atraso"
                )
        else:
            linhas.append("  (nenhuma)")

        linhas += ["", "PRÓXIMAS TAREFAS PENDENTES (até 5)", fina]

        if proximas:
            for titulo, prazo, prioridade, disciplina in proximas:
                linhas.append(
                    f"  - {data_br(prazo)}  {titulo} ({disciplina}) - {prioridade}"
                )
        else:
            linhas.append("  (nenhuma)")

        linhas += [
            "",
            "RESUMOS E FLASH CARDS",
            fina,
            f"  Resumos salvos      : {total_resumos}",
            f"  Flash cards criados : {total_flash}",
            "",
        ]

        return "\n".join(linhas)

# =======================================
# SALVAR O RELATÓRIO EM TXT
# =======================================
    def salvarRelatorio(self, relatorio):
        # Deixa o usuário escolher a pasta e o nome do arquivo
        caminho = filedialog.asksaveasfilename(
            parent=self.janelaRelatorio,
            title="Salvar relatório em arquivo de texto",
            defaultextension=".txt",
            initialfile="relatorio_produtividade",
            filetypes=[("Arquivo de texto", "*.txt")]
        )
        if not caminho:   # o usuário cancelou
            return

        try:
            with open(
                caminho,
                "w",
                encoding="utf-8"
            ) as arquivo:

                arquivo.write(relatorio)

            showinfo(
                "Relatório",
                "Relatório salvo com sucesso!\n"
                f"Arquivo: {caminho}",
                parent=self.janelaRelatorio
            )

        except OSError as erro:

            showerror(
                "Erro ao salvar",
                "Não foi possível salvar o relatório:\n"
                + str(erro),
                parent=self.janelaRelatorio
            )


# *=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=*=


def main():
    criarBanco()
    Login().mainloop()


if __name__ == "__main__":
    main()

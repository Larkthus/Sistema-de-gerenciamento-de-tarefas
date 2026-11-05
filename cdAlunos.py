import sqlite3
conexao = sqlite3.connect("cadastros.db")

comando = """
CREATE TABLE IF NOT EXISTS logins (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    nome TEXT NOT NULL,
    senha TEXT NOT NULL,
    matricula TEXT NOT NULL UNIQUE
)
"""

conexao.execute(comando)
conexao.commit()
conexao.close()
print("Banco de dados preparado com sucesso!") 

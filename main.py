cat > /mnt/user-data/outputs/main.py << 'EOF'
"""
FastAPI wrapper para Analise CLT Bankarize - VERSÃO 2

Endpoints:
  POST /simular - Simula crédito para um CPF
  GET /health - Health check
"""

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import os
import sys
from autocontratacao import fluxo_completo, ReprovadoError

# Carrega variáveis de ambiente
REFERRAL_LINK_DEFAULT = os.getenv("BANKARIZE_REFERRAL_LINK", None)

app = FastAPI(
    title="Analise CLT Bankarize",
    description="API para análise e simulação de crédito CLT via Bankarize",
    version="2.0.0"
)


class SimularRequest(BaseModel):
    cpf: str
    nome: str = "Cliente Corban"
    referral_link: str = None


def formatar_anotacao_sucesso(detalhes, simulacao, cliente_info):
    """Formata uma anotação legível para o vendedor."""
    nome = detalhes.get("workerName", "Cliente")
    cpf = detalhes.get("workerDocumentNumber", "")
    empresa = detalhes.get("employerName", "")
    margem = detalhes.get("availableMarginValue", 0)
    rendimento = detalhes.get("totalEarnings", 0)
    
    anotacao = f"""✅ PRÉ-APROVADO PARA CRÉDITO CLT

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
DADOS DO CLIENTE
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Nome: {nome}
CPF: {cpf}
Empresa: {empresa}
Margem Disponível: R$ {margem:,.2f}
Rendimento Total: R$ {rendimento:,.2f}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
OPÇÕES DE CRÉDITO DISPONÍVEIS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""
    
    # Adiciona cada simulação
    tabelas = simulacao.get("data", [])
    opcao_num = 1
    for tab in tabelas:
        if not tab.get("error"):
            table_name = tab.get("table", {}).get("name", "")
            term = tab.get("table", {}).get("term", 0)
            payload = tab.get("simulation", {}).get("payload", {})
            valor = payload.get("gross_value", 0)
            parcela = payload.get("installment_value", 0)
            
            # Formata prazo de forma legível
            if term == 12:
                prazo_texto = "1 ANO"
            elif term == 24:
                prazo_texto = "2 ANOS"
            elif term == 18:
                prazo_texto = "1 ANO E 6 MESES"
            elif term == 15:
                prazo_texto = "1 ANO E 3 MESES"
            else:
                prazo_texto = f"{term} MESES"
            
            anotacao += f"""
📌 OPÇÃO {opcao_num} - {table_name} ({prazo_texto})
   Valor a Receber: R$ {valor:,.2f}
   Parcela Mensal: R$ {parcela:,.2f}
   Total de Parcelas: {term} meses
"""
            opcao_num += 1
    
    anotacao += """
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
✅ Cliente PRÉ-APROVADO - Grupo Somos H
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"""
    
    return anotacao


def extrair_simulacoes(simulacao):
    """Extrai apenas as simulações aprovadas."""
    resultado = []
    tabelas = simulacao.get("data", [])
    
    for tab in tabelas:
        if not tab.get("error"):
            table_name = tab.get("table", {}).get("name", "")
            payload = tab.get("simulation", {}).get("payload", {})
            
            resultado.append({
                "tabela": table_name,
                "valor_liberado": round(payload.get("gross_value", 0), 2),
                "parcela_mensal": round(payload.get("installment_value", 0), 2),
                "prazo_meses": tab.get("table", {}).get("term", 0)
            })
    
    return resultado


@app.get("/health")
async def health():
    """Health check endpoint."""
    return {"status": "ok", "service": "analise-clt-bankarize"}


@app.post("/simular")
async def simular(request: SimularRequest):
    """
    Simula crédito CLT para um CPF.
    
    Retorna:
        - resultado: "pre_aprovado" | "reprovado" | "erro"
        - anotacao: texto formatado para o vendedor ler
        - simulacoes: array com opções disponíveis (só se pre_aprovado)
    """
    try:
        # Limpa CPF
        cpf_limpo = request.cpf.replace(".", "").replace("-", "")
        
        # Define referral_link
        referral_link = request.referral_link or REFERRAL_LINK_DEFAULT
        
        print(f"[API] Simulando CPF {cpf_limpo}")
        
        # Executa o fluxo completo
        resultado_completo = fluxo_completo(cpf_limpo, request.nome, referral_link)
        
        # Se chegou aqui, é sucesso
        # Extrai dados para formatar resposta
        detalhes = resultado_completo.get("detalhes", {})
        simulacao = resultado_completo.get("simulacao", {})
        email = resultado_completo.get("email", "")
        senha = resultado_completo.get("senha", "")
        
        # Monta a anotação legível
        anotacao = formatar_anotacao_sucesso(detalhes, simulacao, resultado_completo)
        
        # Extrai simulações
        simulacoes = extrair_simulacoes(simulacao)
        
        return {
            "resultado": "pre_aprovado",
            "anotacao": anotacao,
            "email": email,
            "senha": senha,
            "simulacoes": simulacoes
        }
        
    except ReprovadoError as e:
        # Reprovação de negócio
        return {
            "resultado": "reprovado",
            "anotacao": f"❌ NÃO APROVADO\n\nMotivo: {str(e)}"
        }
    
    except Exception as e:
        print(f"[API-ERROR] {type(e).__name__}: {e}")
        return {
            "resultado": "erro",
            "anotacao": f"⚠️ ERRO NO PROCESSAMENTO\n\n{type(e).__name__}: {str(e)}"
        }


if __name__ == "__main__":
    import uvicorn
    
    host = os.getenv("API_HOST", "0.0.0.0")
    port = int(os.getenv("API_PORT", "8000"))
    workers = int(os.getenv("API_WORKERS", "0"))
    
    print(f"[STARTUP] Iniciando Analise CLT Bankarize API v2.0.0")
    print(f"[STARTUP] Host: {host}:{port}")
    
    if workers > 0:
        uvicorn.run("main:app", host=host, port=port, workers=workers)
    else:
        uvicorn.run(app, host=host, port=port)
EOF
Saída

exit code 0

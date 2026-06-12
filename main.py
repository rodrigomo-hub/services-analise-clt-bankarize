"""
FastAPI wrapper para Analise CLT Bankarize - VERSÃO 3.1.0

Síncrono com Timeout + Workers paralelos
Sem fila, sem complicação no n8n

Porta: 8002
"""

import logging
import asyncio
import os

import uvicorn
from fastapi import FastAPI
from pydantic import BaseModel
from autocontratacao import fluxo_completo, ReprovadoError

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

# ── App ──────────────────────────────────────────────────────────────────────

app = FastAPI(
    title="Analise CLT Bankarize",
    description="API para análise e simulação de crédito CLT via Bankarize",
    version="3.1.0"
)


# ── Schemas ──────────────────────────────────────────────────────────────────

class SimularRequest(BaseModel):
    cpf: str
    nome: str = "Cliente Corban"
    referral_link: str = None


def formatar_anotacao_sucesso(detalhes, simulacao):
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
    
    tabelas = simulacao.get("data", [])
    opcao_num = 1
    for tab in tabelas:
        if not tab.get("error"):
            table_name = tab.get("table", {}).get("name", "")
            term = tab.get("table", {}).get("term", 0)
            payload = tab.get("simulation", {}).get("payload", {})
            valor = payload.get("net_value", 0)
            parcela = payload.get("installment_value", 0)
            
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
                "valor_liberado": round(payload.get("net_value", 0), 2),
                "parcela_mensal": round(payload.get("installment_value", 0), 2),
                "prazo_meses": tab.get("table", {}).get("term", 0)
            })
    
    return resultado


# ── Endpoints ────────────────────────────────────────────────────────────────

@app.get("/health")
async def health():
    """Health check endpoint."""
    return {
        "status": "ok",
        "service": "analise-clt-bankarize",
        "version": "3.1.0"
    }


@app.post("/simular")
async def simular(request: SimularRequest):
    """
    Simula crédito CLT para um CPF.
    
    Processa de forma síncrona com timeout de 120s.
    Se exceder timeout, retorna erro para retry.
    
    Retorna:
        - resultado: "pre_aprovado" | "reprovado" | "erro"
        - anotacao: texto formatado para o vendedor ler
        - simulacoes: array com opções disponíveis (só se pre_aprovado)
    """
    try:
        cpf_limpo = request.cpf.replace(".", "").replace("-", "")
        referral_link = request.referral_link
        
        logger.info(f"[API] Simulando CPF {cpf_limpo}")
        
        # Executa com timeout de 120 segundos
        resultado_completo = await asyncio.wait_for(
            asyncio.get_event_loop().run_in_executor(
                None,
                lambda: fluxo_completo(cpf_limpo, request.nome, referral_link)
            ),
            timeout=120.0
        )
        
        # Se chegou aqui, é sucesso
        detalhes = resultado_completo.get("detalhes", {})
        simulacao = resultado_completo.get("simulacao", {})
        email = resultado_completo.get("email", "")
        senha = resultado_completo.get("senha", "")
        
        anotacao = formatar_anotacao_sucesso(detalhes, simulacao)
        simulacoes = extrair_simulacoes(simulacao)
        
        return {
            "resultado": "pre_aprovado",
            "anotacao": anotacao,
            "email": email,
            "senha": senha,
            "simulacoes": simulacoes
        }
        
    except asyncio.TimeoutError:
        logger.warning(f"[API-TIMEOUT] Excedeu 120s")
        return {
            "resultado": "erro",
            "anotacao": "⚠️ ERRO NO PROCESSAMENTO\n\nTimeout - Processamento demorou muito. Tente novamente em alguns momentos."
        }
    
    except ReprovadoError as e:
        return {
            "resultado": "reprovado",
            "anotacao": f"❌ NÃO APROVADO\n\nMotivo: {str(e)}"
        }
    
    except Exception as e:
        logger.exception(f"[API-ERROR] {type(e).__name__}: {e}")
        return {
            "resultado": "erro",
            "anotacao": f"⚠️ ERRO NO PROCESSAMENTO\n\n{type(e).__name__}: {str(e)}"
        }


if __name__ == "__main__":
    host = os.getenv("API_HOST", "0.0.0.0")
    port = int(os.getenv("API_PORT", "8002"))
    workers = int(os.getenv("API_WORKERS", "4"))
    
    print(f"[STARTUP] Iniciando Analise CLT Bankarize API v3.1.0")
    print(f"[STARTUP] Host: {host}:{port} | Workers: {workers}")
    
    uvicorn.run("main:app", host=host, port=port, workers=workers)

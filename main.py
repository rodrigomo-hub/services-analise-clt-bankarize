"""
FastAPI wrapper para Analise CLT Bankarize

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
    version="1.0.0"
)


class SimularRequest(BaseModel):
    cpf: str
    nome: str = "Cliente Corban"
    referral_link: str = None  # opcional — usa padrão se não informado


class SimularResponse(BaseModel):
    status: str
    cpf: str
    email: str = None
    employer_name: str = None
    available_margin: float = None
    melhor_tabela: str = None
    melhor_tabela_net_value: float = None
    motivo: str = None  # para reprovações
    erro: str = None  # para erros técnicos


@app.get("/health")
async def health():
    """Health check endpoint."""
    return {"status": "ok", "service": "analise-clt-bankarize"}


@app.post("/simular", response_model=dict)
async def simular(request: SimularRequest):
    """
    Simula crédito CLT para um CPF.
    
    Args:
        cpf: CPF do cliente (com ou sem formatação)
        nome: Nome do cliente (padrão: "Cliente Corban")
        referral_link: URL de referral com parâmetro R= (opcional)
    
    Returns:
        dict com resultado da simulação
    
    Status retornado:
        - "sucesso": simulação realizada com oferta válida
        - "sem_oferta": simulação ok mas sem oferta viável (margem < R$1000)
        - "reprovado": CPF processado mas reprovado pelos fundos
        - "erro": erro técnico durante o fluxo
    """
    try:
        # Limpa CPF
        cpf_limpo = request.cpf.replace(".", "").replace("-", "")
        
        # Define referral_link (prioridade: requisição > ENV > None)
        referral_link = request.referral_link or REFERRAL_LINK_DEFAULT
        
        print(f"[API] Simulando CPF {cpf_limpo} com link: {referral_link}")
        
        # Executa o fluxo
        resultado = fluxo_completo(cpf_limpo, request.nome, referral_link)
        
        return resultado
        
    except ReprovadoError as e:
        # Reprovação de negócio (não é erro técnico)
        return {
            "status": "reprovado",
            "cpf": cpf_limpo,
            "motivo": str(e)
        }
    
    except Exception as e:
        print(f"[API-ERROR] {type(e).__name__}: {e}")
        return {
            "status": "erro",
            "cpf": cpf_limpo,
            "erro": f"{type(e).__name__}: {str(e)}"
        }


@app.post("/simular-lote")
async def simular_lote(cpfs: list[str], nome: str = "Cliente Corban", referral_link: str = None):
    """
    Simula crédito para múltiplos CPFs em lote.
    
    Args:
        cpfs: Lista de CPFs
        nome: Nome padrão dos clientes
        referral_link: URL de referral com parâmetro R= (opcional)
    
    Returns:
        list de resultados (um por CPF)
    """
    resultados = []
    
    for idx, cpf in enumerate(cpfs, 1):
        try:
            cpf_limpo = cpf.replace(".", "").replace("-", "")
            print(f"[LOTE] Processando {idx}/{len(cpfs)}: {cpf_limpo}")
            
            resultado = fluxo_completo(cpf_limpo, nome, referral_link)
            resultados.append(resultado)
            
        except ReprovadoError as e:
            resultados.append({
                "status": "reprovado",
                "cpf": cpf_limpo,
                "motivo": str(e)
            })
        except Exception as e:
            resultados.append({
                "status": "erro",
                "cpf": cpf_limpo,
                "erro": f"{type(e).__name__}: {str(e)}"
            })
    
    # Resumo
    sucessos = sum(1 for r in resultados if r.get("status") == "sucesso")
    reprovados = sum(1 for r in resultados if r.get("status") == "reprovado")
    erros = sum(1 for r in resultados if r.get("status") == "erro")
    
    return {
        "total": len(resultados),
        "sucessos": sucessos,
        "reprovados": reprovados,
        "erros": erros,
        "resultados": resultados
    }


if __name__ == "__main__":
    import uvicorn
    
    # Configurações via ENV ou defaults
    host = os.getenv("API_HOST", "0.0.0.0")
    port = int(os.getenv("API_PORT", "8000"))
    workers = int(os.getenv("API_WORKERS", "1"))
    
    print(f"[STARTUP] Iniciando Analise CLT Bankarize API")
    print(f"[STARTUP] Host: {host}:{port}")
    print(f"[STARTUP] Workers: {workers}")
    
    uvicorn.run(app, host=host, port=port, workers=workers)

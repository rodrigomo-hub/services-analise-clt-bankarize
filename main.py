"""
FastAPI wrapper para Analise CLT Bankarize - VERSÃO 3.0.0

Fila persistente em arquivo + Worker background
Sem risco de travamento com múltiplas requisições

Porta: 8002
"""

import logging
import asyncio
import json
import os
import time
from typing import Optional

import uvicorn
from fastapi import FastAPI
from pydantic import BaseModel
from autocontratacao import fluxo_completo, ReprovadoError

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

# ── Arquivos de fila ─────────────────────────────────────────────────────────

BASE_DIR = "/opt/analise-clt-bankarize"
FILA_SIMULACOES = os.path.join(BASE_DIR, "fila_simulacoes.json")
RESULTADOS_CACHE = os.path.join(BASE_DIR, "resultados_cache.json")
FALHAS = os.path.join(BASE_DIR, "falhas.json")

os.makedirs(BASE_DIR, exist_ok=True)

_fila_lock = asyncio.Lock()


def _ler(path: str) -> list:
    try:
        if os.path.exists(path):
            with open(path, "r") as f:
                return json.load(f)
    except Exception:
        pass
    return []


def _salvar(path: str, data: list):
    with open(path, "w") as f:
        json.dump(data, f, indent=2)


def _enfileirar(cpf: str, nome: str, referral_link: Optional[str]):
    """Adiciona à fila de simulação."""
    fila = _ler(FILA_SIMULACOES)
    
    item = {
        "cpf": cpf,
        "nome": nome,
        "referral_link": referral_link,
        "ts": time.time(),
        "id": f"{cpf}_{int(time.time())}"
    }
    
    # Evita duplicados
    if not any(x["cpf"] == cpf and x["ts"] > time.time() - 60 for x in fila):
        fila.append(item)
        _salvar(FILA_SIMULACOES, fila)
        logger.info(f"[FILA] Enfileirado: {cpf}")
    
    return item["id"]


def _registrar_resultado(cpf: str, resultado: dict):
    """Salva resultado no cache."""
    cache = _ler(RESULTADOS_CACHE)
    
    # Remove resultado antigo do mesmo CPF
    cache = [c for c in cache if c.get("cpf") != cpf]
    
    resultado["cpf"] = cpf
    resultado["ts"] = time.time()
    cache.append(resultado)
    
    _salvar(RESULTADOS_CACHE, cache)
    logger.info(f"[CACHE] Resultado salvo: {cpf}")


def _registrar_falha(cpf: str, motivo: str):
    """Salva falha."""
    falhas = _ler(FALHAS)
    
    falhas = [f for f in falhas if f["cpf"] != cpf]
    falhas.append({
        "cpf": cpf,
        "motivo": motivo,
        "ts": time.time()
    })
    
    _salvar(FALHAS, falhas)
    logger.warning(f"[FALHA] {cpf}: {motivo}")


# ── Worker background ────────────────────────────────────────────────────────

async def worker_simulacoes():
    logger.info("[Worker] Iniciado.")
    
    while True:
        cpf_processando = None
        
        async with _fila_lock:
            fila = _ler(FILA_SIMULACOES)
            if fila:
                item = fila[0]
                cpf_processando = item["cpf"]
                fila.pop(0)
                _salvar(FILA_SIMULACOES, fila)
        
        if cpf_processando:
            # Busca item completo
            fila = _ler(FILA_SIMULACOES)
            item = next(
                (x for x in _ler(FILA_SIMULACOES) if x["cpf"] == cpf_processando),
                None
            )
            
            if not item:
                # Item já foi processado, pega da fila original
                continue
            
            logger.info(f"[Worker] Processando: {cpf_processando}")
            
            try:
                resultado = await asyncio.get_event_loop().run_in_executor(
                    None,
                    lambda: fluxo_completo(
                        cpf_processando,
                        item.get("nome", "Cliente Corban"),
                        item.get("referral_link")
                    )
                )
                
                # Processa resultado (mesmo do endpoint /simular)
                detalhes = resultado.get("detalhes", {})
                simulacao = resultado.get("simulacao", {})
                email = resultado.get("email", "")
                senha = resultado.get("senha", "")
                
                anotacao = formatar_anotacao_sucesso(detalhes, simulacao)
                simulacoes = extrair_simulacoes(simulacao)
                
                resultado_final = {
                    "resultado": "pre_aprovado",
                    "anotacao": anotacao,
                    "email": email,
                    "senha": senha,
                    "simulacoes": simulacoes
                }
                
                _registrar_resultado(cpf_processando, resultado_final)
                logger.info(f"[Worker] Sucesso: {cpf_processando}")
                
            except ReprovadoError as e:
                resultado_final = {
                    "resultado": "reprovado",
                    "anotacao": f"❌ NÃO APROVADO\n\nMotivo: {str(e)}"
                }
                _registrar_resultado(cpf_processando, resultado_final)
                logger.warning(f"[Worker] Reprovado: {cpf_processando}")
                
            except Exception as e:
                logger.exception(f"[Worker] Erro: {cpf_processando}")
                _registrar_falha(cpf_processando, str(e))
        
        else:
            await asyncio.sleep(2)


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


# ── App ──────────────────────────────────────────────────────────────────────

app = FastAPI(
    title="Analise CLT Bankarize",
    description="API para análise e simulação de crédito CLT via Bankarize - com fila",
    version="3.0.0"
)


@app.on_event("startup")
async def startup():
    asyncio.create_task(worker_simulacoes())
    logger.info("[API] Worker iniciado.")


# ── Schemas ──────────────────────────────────────────────────────────────────

class SimularRequest(BaseModel):
    cpf: str
    nome: str = "Cliente Corban"
    referral_link: str = None


# ── Endpoints ────────────────────────────────────────────────────────────────

@app.get("/health")
async def health():
    """Health check endpoint."""
    return {
        "status": "ok",
        "service": "analise-clt-bankarize",
        "version": "3.0.0",
        "fila_total": len(_ler(FILA_SIMULACOES)),
        "cache_resultados": len(_ler(RESULTADOS_CACHE)),
        "falhas_total": len(_ler(FALHAS))
    }


@app.post("/simular")
async def simular(request: SimularRequest):
    """
    Simula crédito CLT para um CPF.
    
    Enfileira a requisição e retorna imediatamente.
    Resultado pode ser consultado via /resultado/{cpf}
    
    Retorna:
        - id: identificador da tarefa
        - status: "enfileirado"
    """
    cpf_limpo = request.cpf.replace(".", "").replace("-", "")
    
    task_id = _enfileirar(cpf_limpo, request.nome, request.referral_link)
    
    return {
        "id": task_id,
        "status": "enfileirado",
        "cpf": cpf_limpo,
        "mensagem": "Requisição enfileirada. Consulte /resultado/{cpf} para ver o resultado."
    }


@app.get("/resultado/{cpf}")
async def resultado(cpf: str):
    """Consulta resultado de uma simulação."""
    cpf_limpo = cpf.replace(".", "").replace("-", "")
    
    cache = _ler(RESULTADOS_CACHE)
    resultado = next((r for r in cache if r.get("cpf") == cpf_limpo), None)
    
    if resultado:
        return resultado
    
    # Verifica se está na fila ainda
    fila = _ler(FILA_SIMULACOES)
    if any(x["cpf"] == cpf_limpo for x in fila):
        return {
            "status": "processando",
            "cpf": cpf_limpo,
            "mensagem": "Ainda está sendo processado. Tente novamente em alguns segundos."
        }
    
    # Verifica falhas
    falhas = _ler(FALHAS)
    falha = next((f for f in falhas if f.get("cpf") == cpf_limpo), None)
    
    if falha:
        return {
            "resultado": "erro",
            "anotacao": f"⚠️ ERRO NO PROCESSAMENTO\n\n{falha['motivo']}"
        }
    
    return {
        "status": "nao_encontrado",
        "cpf": cpf_limpo,
        "mensagem": "Nenhum resultado encontrado para este CPF."
    }


@app.get("/fila")
async def ver_fila():
    """Ver fila de simulações."""
    fila = _ler(FILA_SIMULACOES)
    return {
        "total": len(fila),
        "fila": fila
    }


@app.get("/falhas")
async def ver_falhas():
    """Ver simulações que falharam."""
    falhas = _ler(FALHAS)
    return {
        "total": len(falhas),
        "falhas": falhas
    }


@app.delete("/falhas")
async def limpar_falhas():
    """Limpar registro de falhas."""
    _salvar(FALHAS, [])
    return {"status": "ok", "mensagem": "Falhas limpas."}


if __name__ == "__main__":
    import uvicorn
    
    host = os.getenv("API_HOST", "0.0.0.0")
    port = int(os.getenv("API_PORT", "8002"))
    
    print(f"[STARTUP] Iniciando Analise CLT Bankarize API v3.0.0")
    print(f"[STARTUP] Host: {host}:{port}")
    
    uvicorn.run(app, host=host, port=port)

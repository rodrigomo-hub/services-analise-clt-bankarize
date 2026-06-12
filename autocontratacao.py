"""
Automação - Autocontratação eConsignado (Bankerize / Grupo H / Somos H)

Fluxo:
1. identify-cpf -> verifica se CPF já tem conta
2. (se 404) cria usuário com dados aleatórios (nome, email, telefone) + senha padrão
3. login -> obtém JWT (Bearer token)
4. accept-terms
5. employment-relationship -> solicita consulta de vínculo
6. polling em /employment-relationships até queueSituation == 1 (elegível)
7. employment-relationship/details -> detalhes (margem disponível etc)
8. simulate -> tabelas de simulação

Uso:
    python autocontratacao.py <CPF>
"""

import requests
import random
import string
import time
import sys
import json
import os
from urllib.parse import urlparse, parse_qs

BASE_URL = "https://api.bankerize.com.br"
REFERRAL_UUID_DEFAULT = "bf92168d-679a-4be8-9bca-8836cb903179"  # padrão - RB Promotora
SENHA_PADRAO = "padrao123456"
BANK = "bmp"  # banco usado no fluxo econsignado

HEADERS_BASE = {
    "Accept": "application/json",
    "Content-Type": "application/json",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/148.0.0.0 Safari/537.36",
    "Origin": "https://app.somosh.com.br",
    "Referer": "https://app.somosh.com.br/",
}


class ReprovadoError(Exception):
    """CPF processado com sucesso, mas reprovado pelas regras dos fundos (resultado de negócio definitivo)."""
    pass


def extrair_referral_uuid(referral_link):
    """Extrai o parâmetro R= da URL do link de autocontratação."""
    if not referral_link:
        return REFERRAL_UUID_DEFAULT
    
    try:
        parsed = urlparse(referral_link)
        params = parse_qs(parsed.query)
        uuid = params.get('R', [REFERRAL_UUID_DEFAULT])[0]
        return uuid if uuid else REFERRAL_UUID_DEFAULT
    except Exception as e:
        print(f"[aviso] erro ao extrair UUID do link: {e}, usando padrão")
        return REFERRAL_UUID_DEFAULT


def gerar_string_aleatoria(tamanho=8):
    return "".join(random.choices(string.ascii_lowercase + string.digits, k=tamanho))


def gerar_email_aleatorio(cpf=None):
    if cpf:
        return f"cliente{cpf}@gmail.com"
    return f"cliente.{gerar_string_aleatoria(10)}@gmail.com"


def gerar_telefone_aleatorio():
    # DDD aleatório válido + 9 dígitos
    ddd = random.choice(["11", "21", "31", "41", "51", "61", "71", "81", "91"])
    numero = "9" + "".join(random.choices(string.digits, k=8))
    return ddd + numero


def identify_cpf(session, cpf):
    """Verifica se o CPF já possui conta. Retorna True se existe, False se 404 (não existe)."""
    url = f"{BASE_URL}/auth/self-service/identify-cpf"
    resp = session.post(url, json={"cpf": cpf}, headers=HEADERS_BASE)
    print(f"[identify-cpf] status={resp.status_code} body={resp.text}")
    if resp.status_code == 404:
        return False
    if resp.status_code == 200:
        return True
    resp.raise_for_status()


def criar_usuario(session, cpf, nome):
    """Cria novo usuário (cliente) com email baseado em CPF e senha padrão. Retorna (email, senha)."""
    email = gerar_email_aleatorio(cpf)  # cliente{cpf}@gmail.com
    telefone = gerar_telefone_aleatorio()
    senha = f"cliente{cpf}"  # senha padrão: cliente{cpf}

    url = f"{BASE_URL}/admin/self-service/users"
    payload = {
        "cpf": cpf,
        "name": nome,
        "email": email,
        "phone": telefone,
        "password": senha,
    }
    resp = session.post(url, json=payload, headers=HEADERS_BASE)
    print(f"[criar-usuario] status={resp.status_code} body={resp.text}")
    resp.raise_for_status()

    return email, senha


def login(session, email, senha, referral_uuid=None):
    """Realiza login e retorna o JWT token."""
    if referral_uuid is None:
        referral_uuid = REFERRAL_UUID_DEFAULT
    
    url = f"{BASE_URL}/auth/self-service/login"
    payload = {
        "email": email,
        "password": senha,
        "user_referral_uuid": referral_uuid,
    }
    resp = session.post(url, json=payload, headers=HEADERS_BASE)
    print(f"[login] status={resp.status_code} body={resp.text}")
    resp.raise_for_status()

    data = resp.json()
    token = data["data"]["token"]
    return token


def auth_headers(token):
    h = HEADERS_BASE.copy()
    h["Authorization"] = f"Bearer {token}"
    return h


def accept_terms(session, token):
    url = f"{BASE_URL}/proposals/self-service/accept-terms"
    resp = session.post(url, json={"organ_name": "econsignado"}, headers=auth_headers(token))
    print(f"[accept-terms] status={resp.status_code} body={resp.text}")
    # 201 = aceito agora, outros status podem indicar já aceito anteriormente - não falhar
    return resp


def solicitar_employment_relationship(session, token, cpf):
    url = f"{BASE_URL}/proposals/self-service/econsignado/employment-relationship"
    resp = session.post(url, json={"bank": BANK, "cpf": cpf}, headers=auth_headers(token))
    print(f"[employment-relationship] status={resp.status_code} body={resp.text}")
    resp.raise_for_status()

    data = resp.json()
    return data["data"]["request_uuid"]


def listar_employment_relationships(session, token, request_uuid, max_tentativas=20, intervalo=3):
    """Lista os vínculos retornados (primeira consulta, antes de 'clicar').

    Faz polling até a lista deixar de estar vazia (a consulta inicial é assíncrona).
    """
    url = f"{BASE_URL}/proposals/self-service/econsignado/{request_uuid}/employment-relationships"

    for tentativa in range(1, max_tentativas + 1):
        resp = session.get(url, headers=auth_headers(token))
        resp.raise_for_status()
        data = resp.json().get("data", [])

        print(f"[list-employment {tentativa}/{max_tentativas}] {len(data)} vinculo(s) encontrados")

        if data:
            return data

        time.sleep(intervalo)

    return []


def poll_employment_relationships(session, token, request_uuid, vinculo_uuid, max_tentativas=40, intervalo=5):
    """Faz polling no vínculo específico (por 'uuid') até queueSituation == 1."""
    url = f"{BASE_URL}/proposals/self-service/econsignado/{request_uuid}/employment-relationships"

    ultima_situacao = None

    for tentativa in range(1, max_tentativas + 1):
        resp = session.get(url, headers=auth_headers(token))
        resp.raise_for_status()
        data = resp.json().get("data", [])

        item = next((i for i in data if i.get("uuid") == vinculo_uuid), None)
        if item is None:
            raise RuntimeError(f"Vínculo {vinculo_uuid} não encontrado na lista")

        situacao = item.get("queueSituation")
        if situacao != ultima_situacao:
            print(f"[poll-employment {tentativa}/{max_tentativas}] queueSituation={situacao}")
            ultima_situacao = situacao
        else:
            print(f"[poll-employment {tentativa}/{max_tentativas}] sem mudança ({situacao})")

        if situacao == 1:
            return item
        if situacao == 2:
            motivo = "Motivo não especificado"
            if isinstance(item.get("payload"), dict):
                motivo = item["payload"].get("errorMessage", motivo)
            raise ReprovadoError(f"Vínculo reprovado pelos fundos: {motivo}")
        if item.get("eligible") is False:
            raise RuntimeError(f"CPF não elegível: {item.get('ineligibilityReason')}")

        time.sleep(intervalo)

    raise TimeoutError("Timeout aguardando processamento do vínculo empregatício")


def detalhes_employment_relationship(session, token, request_uuid, registration, employer_document):
    url = f"{BASE_URL}/proposals/self-service/econsignado/employment-relationship/details"
    payload = {
        "request_uuid": request_uuid,
        "registration": registration,
        "employer_document": employer_document,
    }
    resp = session.post(url, json=payload, headers=auth_headers(token))
    print(f"[employment-details] status={resp.status_code} body={resp.text}")
    resp.raise_for_status()
    return resp.json()


def poll_employment_details(session, token, employment_request_uuid, max_tentativas=15, intervalo=3):
    """Faz polling em /employment-relationship/{uuid}/details até retornar dados completos."""
    url = f"{BASE_URL}/proposals/self-service/econsignado/employment-relationship/{employment_request_uuid}/details"

    for tentativa in range(1, max_tentativas + 1):
        resp = session.get(url, headers=auth_headers(token))
        print(f"[poll-details {tentativa}/{max_tentativas}] status={resp.status_code} body={resp.text}")
        if resp.status_code == 200:
            data = resp.json().get("data")
            if data and data.get("employerName"):
                return data
        time.sleep(intervalo)

    raise TimeoutError("Timeout aguardando detalhes do vínculo empregatício")


def simular(session, token, cpf, installment_value, request_uuid):
    url = f"{BASE_URL}/proposals/self-service/econsignado/simulate"
    payload = {
        "cpf": cpf,
        "installment_value": installment_value,
        "bank": BANK,
        "request_uuid": request_uuid,
    }
    resp = session.post(url, json=payload, headers=auth_headers(token))
    print(f"[simulate] status={resp.status_code}")
    resp.raise_for_status()
    return resp.json()


def fluxo_completo(cpf, nome="Cliente Corban", referral_link=None):
    session = requests.Session()
    
    # Extrai o UUID do link, ou usa padrão
    referral_uuid = extrair_referral_uuid(referral_link)

    # 1. Identifica CPF
    ja_existe = identify_cpf(session, cpf)

    if not ja_existe:
        # 2. Cria usuário com email/senha padrão baseado em CPF
        email, senha = criar_usuario(session, cpf, nome)
        # Login do novo usuário
        token = login(session, email, senha, referral_uuid)
    else:
        # CPF já existe - tenta com padrão (cliente{cpf}@gmail.com / cliente{cpf})
        print(f"[login-fallback] CPF já existe, tentando com email/senha padrão")
        email = gerar_email_aleatorio(cpf)  # cliente{cpf}@gmail.com
        senha = f"cliente{cpf}"
        
        try:
            # Testa se o padrão funciona
            token = login(session, email, senha, referral_uuid)
        except Exception as e:
            raise NotImplementedError(
                f"CPF já possui conta cadastrada. Email padrão '{email}' não funciona. "
                f"Erro: {e}"
            )

    # 4. Aceita termos
    accept_terms(session, token)

    # 5. Solicita consulta de vínculo empregatício
    request_uuid = solicitar_employment_relationship(session, token, cpf)

    # 6. Lista vínculos retornados (queueSituation ainda None nesse ponto)
    vinculos = listar_employment_relationships(session, token, request_uuid)
    if not vinculos:
        raise RuntimeError("Nenhum vínculo empregatício encontrado para este CPF")

    # Escolhe o primeiro vínculo elegível (= "clicar nele" na UI)
    vinculo_escolhido = next((v for v in vinculos if v.get("eligible")), None)
    if vinculo_escolhido is None:
        raise RuntimeError("Nenhum vínculo elegível encontrado")

    print("\n>>> Vínculo escolhido:")
    print(json.dumps(vinculo_escolhido, indent=2, ensure_ascii=False))

    registration = vinculo_escolhido["registration"]
    employer_document = vinculo_escolhido["employerDocumentNumber"]
    vinculo_uuid = vinculo_escolhido["uuid"]

    # 7. "Clica" no vínculo -> solicita detalhamento (gera novo request_uuid de fila)
    resp_details = detalhes_employment_relationship(session, token, request_uuid, registration, employer_document)
    employment_request_uuid = resp_details["data"]["request_uuid"]

    # 8. Polling no vínculo escolhido até queueSituation == 1
    vinculo = poll_employment_relationships(session, token, request_uuid, vinculo_uuid)
    print("\n>>> Vínculo pronto:")
    print(json.dumps(vinculo, indent=2, ensure_ascii=False))

    # 9. Polling nos detalhes completos (margem, dados pessoais, etc)
    detalhes = poll_employment_details(session, token, employment_request_uuid)
    print("\n>>> Detalhes do vínculo:")
    print(json.dumps(detalhes, indent=2, ensure_ascii=False))

    margem_disponivel = detalhes["availableMarginValue"]
    print(f"\n>>> Margem disponível: R$ {margem_disponivel}")

    # 10. Simulação usando a margem disponível como valor de parcela
    simulacao = simular(session, token, cpf, margem_disponivel, employment_request_uuid)
    print("\n>>> Resultado da simulação:")
    print(json.dumps(simulacao, indent=2, ensure_ascii=False))

    return {
        "token": token,
        "email": email,
        "senha": senha,
        "vinculo": vinculo,
        "detalhes": detalhes,
        "simulacao": simulacao,
    }


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Uso:")
        print("  python autocontratacao.py <CPF>            -> roda 1 CPF")
        print("  python autocontratacao.py --lote <arquivo> -> roda lista de CPFs (um por linha)")
        sys.exit(1)

    if sys.argv[1] == "--lote":
        if len(sys.argv) < 3:
            print("Uso: python autocontratacao.py --lote cpfs.txt")
            sys.exit(1)

        arquivo_entrada = sys.argv[2]
        delay = float(sys.argv[3]) if len(sys.argv) > 3 else 3.0

        with open(arquivo_entrada, "r", encoding="utf-8") as f:
            cpfs = [linha.strip().replace(".", "").replace("-", "") for linha in f if linha.strip()]

        print(f"\n>>> {len(cpfs)} CPF(s) carregados de {arquivo_entrada}. Delay entre execuções: {delay}s\n")

        resultados = []

        for idx, cpf in enumerate(cpfs, start=1):
            print(f"\n{'='*60}")
            print(f"[{idx}/{len(cpfs)}] CPF: {cpf}")
            print(f"{'='*60}")

            registro = {"cpf": cpf}

            try:
                resultado = fluxo_completo(cpf)

                vinculo = resultado["vinculo"]
                detalhes = resultado["detalhes"]
                simulacao = resultado["simulacao"]

                melhor_tabela = None
                if simulacao.get("data"):
                    melhor_tabela = max(
                        (item for item in simulacao["data"] if not item.get("error")),
                        key=lambda i: i["table"]["term"],
                        default=None,
                    )

                registro.update({
                    "status": "sucesso",
                    "email": resultado["email"],
                    "senha": resultado["senha"],
                    "employer_name": detalhes.get("employerName"),
                    "employer_document": detalhes.get("employerDocumentNumber"),
                    "available_margin": detalhes.get("availableMarginValue"),
                    "base_margin": detalhes.get("baseMarginValue"),
                    "total_earnings": detalhes.get("totalEarnings"),
                    "melhor_tabela": melhor_tabela["table"]["name"] if melhor_tabela else None,
                    "melhor_tabela_net_value": melhor_tabela["simulation"]["payload"]["net_value"] if melhor_tabela else None,
                })

            except ReprovadoError as e:
                registro.update({
                    "status": "reprovado",
                    "motivo": str(e),
                })
                print(f"\n>>> REPROVADO CPF {cpf}: {registro['motivo']}")

            except Exception as e:
                registro.update({
                    "status": "erro",
                    "erro": f"{type(e).__name__}: {e}",
                })
                print(f"\n>>> ERRO no CPF {cpf}: {registro['erro']}")

            resultados.append(registro)

            arquivo_saida = "resultados_lote.json"
            with open(arquivo_saida, "w", encoding="utf-8") as f:
                json.dump(resultados, f, indent=2, ensure_ascii=False)

            if idx < len(cpfs):
                time.sleep(delay)

        print(f"\n>>> Concluído. {len(resultados)} resultado(s) salvos em {arquivo_saida}")

        sucessos = sum(1 for r in resultados if r["status"] == "sucesso")
        reprovados = sum(1 for r in resultados if r["status"] == "reprovado")
        erros = sum(1 for r in resultados if r["status"] == "erro")
        print(f">>> Sucessos: {sucessos} | Reprovados: {reprovados} | Erros: {erros}")

    else:
        cpf_input = sys.argv[1].replace(".", "").replace("-", "")
        referral_link = sys.argv[2] if len(sys.argv) > 2 else None
        resultado = fluxo_completo(cpf_input, referral_link=referral_link)

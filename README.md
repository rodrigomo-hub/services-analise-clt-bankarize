cat /mnt/user-data/outputs/README.md
Saída

# Analise CLT Bankarize

API para análise e simulação de crédito CLT via **Bankarize** (Somos H / Grupo H).

## 🎯 O Que Faz

Automatiza o fluxo de autocontratação eConsignado:

1. Identifica CPF (novo ou existente)
2. Cria/autentica usuário com padrão `cliente{cpf}`
3. Consulta vínculo empregatício
4. Valida elegibilidade
5. Simula crédito e retorna tabelas com margens

## 📊 Taxa de Aprovação

Testado com **123 CPFs**:
- ✅ **18 CPFs com oferta viável** (14,6%)
- ⚠️ **8 CPFs sem oferta** (margem < R$1000) (6,5%)
- ❌ **81 reprovados pelos fundos** (65,8%)
- ❌ **16 erros técnicos** (13%)

## 🚀 Quick Start

### Instalação Local

```bash
# Clone o repo
git clone https://github.com/rodrigomo-hub/services-analise-clt-bankarize.git
cd services-analise-clt-bankarize

# Crie um ambiente virtual
python -m venv venv
source venv/bin/activate  # ou `venv\Scripts\activate` no Windows

# Instale dependências
pip install -r requirements.txt

# Configure o .env (opcional)
cp .env.example .env

# Rode a API
python main.py
```

API estará em: **http://localhost:8000**

Docs interativa (Swagger): **http://localhost:8000/docs**

### Docker (Recomendado para Produção)

```bash
# Build e rode
docker-compose up -d

# Verifique
docker-compose logs -f analise-clt-bankarize
```

API estará em: **http://localhost:8000**

## 📡 Endpoints

### `POST /simular`

Simula crédito para um CPF.

**Request:**
```json
{
  "cpf": "12345678901",
  "nome": "Cliente Corban",
  "referral_link": "https://app.somosh.com.br/autocontratacao/auth/document-check?R=bf92168d-679a-4be8-9bca-8836cb903179"
}
```

**Response (Sucesso):**
```json
{
  "status": "sucesso",
  "cpf": "12345678901",
  "email": "cliente12345678901@gmail.com",
  "senha": "cliente12345678901",
  "employer_name": "EMPRESA LTDA",
  "employer_document": "12345678",
  "available_margin": 1500.00,
  "base_margin": 3000.00,
  "total_earnings": 5000.00,
  "melhor_tabela": "CLT 24x",
  "melhor_tabela_net_value": 4250.00
}
```

**Response (Reprovado):**
```json
{
  "status": "reprovado",
  "cpf": "12345678901",
  "motivo": "Vínculo reprovado pelos fundos: O vínculo não segue as regras de nenhum dos fundos disponíveis."
}
```

**Response (Erro):**
```json
{
  "status": "erro",
  "cpf": "12345678901",
  "erro": "RuntimeError: Nenhum vínculo elegível encontrado"
}
```

### `POST /simular-lote`

Simula múltiplos CPFs em lote.

**Request:**
```json
{
  "cpfs": ["12345678901", "98765432109"],
  "nome": "Cliente Corban",
  "referral_link": "https://..."
}
```

**Response:**
```json
{
  "total": 2,
  "sucessos": 1,
  "reprovados": 0,
  "erros": 1,
  "resultados": [
    { "status": "sucesso", "cpf": "12345678901", ... },
    { "status": "erro", "cpf": "98765432109", ... }
  ]
}
```

### `GET /health`

Health check da API.

**Response:**
```json
{
  "status": "ok",
  "service": "analise-clt-bankarize"
}
```

## ⚙️ Configuração

Crie um arquivo `.env` baseado em `.env.example`:

```env
# API
API_HOST=0.0.0.0
API_PORT=8000
API_WORKERS=2

# Bankarize (opcional - usa padrão se não informado)
BANKARIZE_REFERRAL_LINK=https://app.somosh.com.br/autocontratacao/auth/document-check?R=bf92168d-679a-4be8-9bca-8836cb903179

# Logging
LOG_LEVEL=INFO
```

## 🔐 Padrão de Credenciais

Novos usuários são criados com:
- **Email**: `cliente{cpf}@gmail.com`
- **Senha**: `cliente{cpf}`

Exemplo para CPF `12345678901`:
- Email: `cliente12345678901@gmail.com`
- Senha: `cliente12345678901`

## 🔗 Referral Link

O `referral_link` é dinâmico — extraído automaticamente do parâmetro `R=` da URL.

**Exemplos:**
```
https://app.somosh.com.br/autocontratacao/auth/document-check?R=bf92168d-679a-4be8-9bca-8836cb903179
                                                                  ↑
                                                          UUID extraído automaticamente
```

Se não informado, usa o padrão: `bf92168d-679a-4be8-9bca-8836cb903179` (RB Promotora).

## 📋 Status de Resposta

| Status | Significado |
|--------|------------|
| `sucesso` | Simulação realizada com oferta viável |
| `sem_oferta` | Processada mas margem < R$1000 |
| `reprovado` | CPF elegível mas reprovado pelos fundos |
| `erro` | Erro técnico durante o fluxo |

## 🔍 Motivos de Reprovação (Comuns)

- "O vínculo não segue as regras de nenhum dos fundos disponíveis." (CNAE, elegibilidade)
- "Trustic: Pessoa não encontrada." (dados inconsistentes)
- "Nenhum vínculo elegível encontrado" (sem margem)

## 📦 Estrutura do Projeto

```
.
├── autocontratacao.py       # Script principal de simulação
├── main.py                  # FastAPI wrapper
├── requirements.txt         # Dependências Python
├── Dockerfile              # Container
├── docker-compose.yml      # Orquestração
├── .env.example            # Template de config
└── README.md              # Este arquivo
```

## 🛠️ Desenvolvimento

### Modo Script (CLI)

```bash
# Um CPF
python autocontratacao.py 12345678901

# Com referral_link
python autocontratacao.py 12345678901 "https://app.somosh.com.br/...?R=uuid"

# Lote
python autocontratacao.py --lote cpfs.txt 5
```

### Modo API (FastAPI)

```bash
python main.py
```

Acesse: http://localhost:8000/docs (Swagger)

## 🐳 Deploy em Produção

### Docker Compose

```bash
# Build e rode
docker-compose up -d

# Verifique logs
docker-compose logs -f analise-clt-bankarize

# Parar
docker-compose down
```

### Systemd Service (VPS)

```bash
sudo nano /etc/systemd/system/analise-clt-bankarize.service
```

```ini
[Unit]
Description=Analise CLT Bankarize API
After=network.target

[Service]
Type=simple
User=app
WorkingDirectory=/opt/analise-clt-bankarize
ExecStart=/usr/bin/docker run --rm -p 8000:8000 -e BANKARIZE_REFERRAL_LINK=$REFERRAL_LINK analise-clt-bankarize
Restart=unless-stopped

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable analise-clt-bankarize
sudo systemctl start analise-clt-bankarize
```

## 📚 API Mapeada

**Base URL:** `https://api.bankerize.com.br`

Endpoints internos automatizados:
1. `POST /auth/self-service/identify-cpf` — verifica CPF
2. `POST /admin/self-service/users` — cria usuário
3. `POST /auth/self-service/login` — autentica
4. `POST /proposals/self-service/accept-terms` — aceita termos
5. `POST /proposals/self-service/econsignado/employment-relationship` — solicita vínculo
6. `GET /proposals/self-service/econsignado/{uuid}/employment-relationships` — polling
7. `POST /proposals/self-service/econsignado/employment-relationship/details` — detalhes
8. `POST /proposals/self-service/econsignado/simulate` — simula

## 🔄 Estados de queueSituation

- `null` → aguardando processamento
- `0` → processando
- `1` → **elegível** — dados prontos
- `2` → **reprovado** — motivo em `payload.errorMessage`

## 🧪 Testes

Testado com **123 CPFs** em produção:
- CPFs com vínculo elegível
- CPFs com reprovação de fundos
- CPFs sem margem
- CPFs duplicados (retry com padrão)
- Erros de conexão e timeout

## 🤝 Integração com n8n/Ticketz

Próxima etapa: conectar endpoints desta API ao n8n para orquestração de fluxo completo.

Webhook esperado:
```
POST http://analise-clt-bankarize:8000/simular
```

## 📝 Exemplo cURL

```bash
curl -X POST http://localhost:8000/simular \
  -H "Content-Type: application/json" \
  -d '{
    "cpf": "12345678901",
    "nome": "Teste Client",
    "referral_link": "https://app.somosh.com.br/autocontratacao/auth/document-check?R=bf92168d-679a-4be8-9bca-8836cb903179"
  }'
```

## 📞 Suporte

- **Desenvolvedor**: Rodrigo (Corban)
- **Repositório**: https://github.com/rodrigomo-hub/services-analise-clt-bankarize
- **Última atualização**: Junho 2026

## 📄 Licença

Proprietário - Corban / Grupo H

---

**Status**: ✅ Produção-ready
Concluído

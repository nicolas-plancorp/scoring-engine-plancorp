# Scoring Engine API — Agente 3 Plancorp

API HTTP que expõe o `scoring_engine.py` para consumo pelo Make (WF-3).

## Estrutura

```
scoring_engine_api/
├── app.py                 # Servidor Flask
├── scoring_engine.py      # Lógica de cálculo (Python puro)
├── requirements.txt       # Dependências
├── Procfile               # Comando de start para Render
└── calibracoes/           # 8 YAMLs por produto
    ├── cambio_spot_v1.yaml
    ├── hedge_cambial_v1.yaml
    ├── antecipacao_recebiveis_v1.yaml
    ├── capital_giro_v1.yaml
    ├── acc_ace_v1.yaml
    ├── finimp_v1.yaml
    ├── energia_ml_v1.yaml
    └── folha_pagamento_v1.yaml
```

## Endpoints

### `GET /health`
Health check. Retorna lista de calibragens carregadas.

### `GET /calibragens`
Lista todas as calibragens com resumo de gatilhos e sub-personas.

### `GET /calibragens/<produto>`
Retorna a calibragem completa de um produto. Usado pelo Make para alimentar o prompt do Claude.

### `POST /score`
Endpoint principal — calcula o score.

**Payload:**
```json
{
  "produto": "cambio_spot",
  "firmografico": {
    "cnae_primario": "4632",
    "faturamento_estimado_brl": 35000000,
    "numero_funcionarios": 80,
    "estado": "SP",
    "headcount_anterior": 60,
    "decisor_linkedin_post_dias": 15,
    "decisor_novo_cargo_dias": 45
  },
  "gatilhos_detectados": [
    {
      "gatilho_id": "pagamento_recorrente_fornecedor_exterior",
      "presente": true,
      "confidence": 0.85,
      "data_evidencia": "2026-05-10"
    }
  ],
  "criterios_externos": {
    "exportacao_ativa": true
  }
}
```

**Resposta:**
```json
{
  "score_ia": 87.5,
  "classificacao_ia": "A",
  "acao_sugerida": "abordar_agora",
  "desqualificado": false,
  "razao_desqualificacao": null,
  "detalhes": { ... },
  "produto": "cambio_spot",
  "calibragem_versao": "1.0"
}
```

## Deploy no Render (gratuito)

### 1. Subir código no GitHub
```bash
cd scoring_engine_api
git init
git add .
git commit -m "Initial scoring engine API"
git branch -M main
git remote add origin https://github.com/SEU_USER/scoring-engine-plancorp.git
git push -u origin main
```

### 2. Criar serviço no Render
1. Acesse https://render.com → New + → Web Service
2. Conecte ao repositório GitHub
3. Configurações:
   - **Name:** `scoring-engine-plancorp`
   - **Environment:** `Python 3`
   - **Build Command:** `pip install -r requirements.txt`
   - **Start Command:** `gunicorn app:app --bind 0.0.0.0:$PORT --workers 2 --timeout 60`
   - **Instance Type:** Free
4. Click "Create Web Service"

### 3. Aguardar deploy (~3 min)
URL final: `https://scoring-engine-plancorp.onrender.com`

### 4. Validar
```bash
curl https://scoring-engine-plancorp.onrender.com/health
```

## Teste local

```bash
cd scoring_engine_api
pip install -r requirements.txt
python app.py
# Em outro terminal:
curl http://localhost:5000/health
```

## Observação sobre plano gratuito Render

O plano gratuito do Render dorme após 15 min de inatividade. A primeira requisição
após dormir leva ~30s para acordar (cold start). Para a demo isso é aceitável.

Para produção: upgrade para Starter ($7/mês) elimina o cold start.

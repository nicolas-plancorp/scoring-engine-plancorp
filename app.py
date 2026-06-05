"""
API HTTP do Scoring Engine — Agente 3 Plancorp
Expõe o scoring_engine.py via endpoint REST para consumo pelo Make.
"""

import os
import yaml
import pathlib
from flask import Flask, request, jsonify
from scoring_engine import (
    DadosFirmograficos,
    GatilhoDetectado,
    calcular_score,
    acao_sugerida,
)

app = Flask(__name__)

CALIBRACOES_DIR = pathlib.Path(__file__).parent / "calibracoes"

# Cache das calibragens em memória (carregadas no startup)
_CALIBRACOES_CACHE = {}


def carregar_calibracoes():
    """Carrega todos os YAMLs em memória ao iniciar a API."""
    for yaml_file in CALIBRACOES_DIR.glob("*.yaml"):
        produto = yaml_file.stem.replace("_v1", "")
        with open(yaml_file, encoding="utf-8") as f:
            _CALIBRACOES_CACHE[produto] = yaml.safe_load(f)
    print(f"✓ {len(_CALIBRACOES_CACHE)} calibragens carregadas: {list(_CALIBRACOES_CACHE.keys())}")


carregar_calibracoes()


@app.route("/health", methods=["GET"])
def health():
    """Health check para o Render."""
    return jsonify({
        "status": "ok",
        "calibracoes_carregadas": list(_CALIBRACOES_CACHE.keys()),
        "total": len(_CALIBRACOES_CACHE),
    })


@app.route("/calibragens", methods=["GET"])
def listar_calibracoes():
    """Lista as calibragens disponíveis e seus gatilhos."""
    resumo = {}
    for produto, cal in _CALIBRACOES_CACHE.items():
        resumo[produto] = {
            "nome_completo": cal.get("nome_completo"),
            "versao": cal.get("versao"),
            "gatilhos": [
                {"id": g["id"], "descricao": g["descricao"], "peso": g["peso"]}
                for g in cal.get("gatilhos", [])
            ],
            "sub_personas": [
                {"id": sp["id"], "descricao": sp["descricao"]}
                for sp in cal.get("sub_personas", [])
            ],
        }
    return jsonify(resumo)


@app.route("/calibragens/<produto>", methods=["GET"])
def obter_calibragem(produto):
    """Retorna a calibragem completa de um produto (usado pelo Make para montar prompt)."""
    if produto not in _CALIBRACOES_CACHE:
        return jsonify({
            "erro": f"Produto '{produto}' não encontrado",
            "produtos_disponiveis": list(_CALIBRACOES_CACHE.keys()),
        }), 404
    return jsonify(_CALIBRACOES_CACHE[produto])


@app.route("/score", methods=["POST"])
def calcular():
    """
    Endpoint principal — calcula score de um lead.

    Payload esperado:
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
    """
    try:
        body = request.get_json(force=True)
    except Exception as e:
        return jsonify({"erro": f"JSON inválido: {e}"}), 400

    produto = body.get("produto")
    if not produto:
        return jsonify({"erro": "Campo 'produto' é obrigatório"}), 400

    if produto not in _CALIBRACOES_CACHE:
        return jsonify({
            "erro": f"Produto '{produto}' não tem calibragem",
            "produtos_disponiveis": list(_CALIBRACOES_CACHE.keys()),
        }), 404

    calibragem = _CALIBRACOES_CACHE[produto]

    # Montar DadosFirmograficos
    firm_data = body.get("firmografico", {})
    firmografico = DadosFirmograficos(
        cnae_primario=firm_data.get("cnae_primario"),
        faturamento_estimado_brl=firm_data.get("faturamento_estimado_brl"),
        numero_funcionarios=firm_data.get("numero_funcionarios"),
        estado=firm_data.get("estado"),
        headcount_anterior=firm_data.get("headcount_anterior"),
        decisor_linkedin_post_dias=firm_data.get("decisor_linkedin_post_dias"),
        decisor_novo_cargo_dias=firm_data.get("decisor_novo_cargo_dias"),
    )

    # Montar lista de GatilhoDetectado
    gatilhos_detectados = []
    gatilhos_raw = body.get("gatilhos_detectados", [])
        gatilhos_detectados.append(GatilhoDetectado(
            gatilho_id=g.get("gatilho_id"),
            presente=g.get("presente", False),
            confidence=g.get("confidence", 0.0),
            data_evidencia=g.get("data_evidencia"),
        ))

    criterios_externos = body.get("criterios_externos", {})

    # Calcular
    try:
        resultado = calcular_score(
            firmografico=firmografico,
            gatilhos_detectados=gatilhos_detectados,
            calibragem=calibragem,
            criterios_externos=criterios_externos,
        )
    except Exception as e:
        return jsonify({
            "erro": f"Erro no cálculo: {e}",
            "tipo": type(e).__name__,
        }), 500

    # Resposta enriquecida
    return jsonify({
        "score_ia": resultado.score_total,
        "classificacao_ia": resultado.classificacao,
        "acao_sugerida": acao_sugerida(resultado.score_total),
        "desqualificado": resultado.desqualificado,
        "razao_desqualificacao": resultado.razao_desqualificacao,
        "detalhes": resultado.detalhes,
        "produto": produto,
        "calibragem_versao": calibragem.get("versao"),
    })


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)

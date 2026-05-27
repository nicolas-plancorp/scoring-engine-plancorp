"""
Scoring Engine — Agente 3 Plancorp Capital
Cálculo de score de fit e urgência em Python puro, sem chamadas ao Claude.

Score composto (0–100):
  - Firmográfico  : 0–30 pts
  - Gatilhos      : 0–50 pts
  - Timing        : 0–20 pts
  - Bônus         : até +15 pts (cap no score final: 100)
  - Penalidade    : critério desqualificador → score = 0

Classificação final: A ≥ 80 | B 60–79 | C < 60
"""

from __future__ import annotations

import math
from datetime import date, datetime
from typing import Any


# ─────────────────────────────────────────
# TIPOS
# ─────────────────────────────────────────

class DadosFirmograficos:
    def __init__(
        self,
        cnae_primario: str | None = None,
        faturamento_estimado_brl: float | None = None,
        numero_funcionarios: int | None = None,
        estado: str | None = None,
        headcount_anterior: int | None = None,      # para bônus de crescimento
        decisor_linkedin_post_dias: int | None = None,  # dias desde último post do decisor
        decisor_novo_cargo_dias: int | None = None,     # dias desde início no cargo atual
    ):
        self.cnae_primario = cnae_primario
        self.faturamento_estimado_brl = faturamento_estimado_brl
        self.numero_funcionarios = numero_funcionarios
        self.estado = estado
        self.headcount_anterior = headcount_anterior
        self.decisor_linkedin_post_dias = decisor_linkedin_post_dias
        self.decisor_novo_cargo_dias = decisor_novo_cargo_dias


class GatilhoDetectado:
    def __init__(
        self,
        gatilho_id: str,
        presente: bool,
        confidence: float,          # 0.0–1.0
        data_evidencia: date | str | None = None,
    ):
        self.gatilho_id = gatilho_id
        self.presente = presente
        self.confidence = max(0.0, min(1.0, confidence))
        self.data_evidencia = _parse_date(data_evidencia)


class ResultadoScore:
    def __init__(
        self,
        score_total: float,
        classificacao: str,
        detalhes: dict[str, Any],
        desqualificado: bool = False,
        razao_desqualificacao: str | None = None,
    ):
        self.score_total = round(score_total, 1)
        self.classificacao = classificacao
        self.detalhes = detalhes
        self.desqualificado = desqualificado
        self.razao_desqualificacao = razao_desqualificacao

    def to_dict(self) -> dict:
        return {
            "score_ia": self.score_total,
            "classificacao_ia": self.classificacao,
            "desqualificado": self.desqualificado,
            "razao_desqualificacao": self.razao_desqualificacao,
            "detalhes": self.detalhes,
        }


# ─────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────

def _parse_date(valor: date | str | None) -> date | None:
    if valor is None:
        return None
    if isinstance(valor, date):
        return valor
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%Y/%m/%d"):
        try:
            return datetime.strptime(valor, fmt).date()
        except (ValueError, TypeError):
            continue
    return None


def _dias_desde(dt: date | None) -> int | None:
    if dt is None:
        return None
    return (date.today() - dt).days


# ─────────────────────────────────────────
# COMPONENTES DO SCORE
# ─────────────────────────────────────────

# Regiões classificadas por concentração de middle-market
_REGIOES_SCORE = {
    "SP": 5, "RJ": 4, "MG": 4, "PR": 4, "RS": 4, "SC": 4,
    "GO": 3, "ES": 3, "BA": 3, "PE": 3, "CE": 3, "MT": 3, "MS": 3,
    "PA": 2, "AM": 2, "DF": 3, "RN": 2, "PB": 2, "MA": 2, "PI": 2,
    "AL": 1, "SE": 1, "RO": 1, "TO": 1, "AC": 1, "AP": 1, "RR": 1,
}


def _score_firmografico(
    firmografico: DadosFirmograficos,
    calibragem: dict,
) -> tuple[float, dict]:
    """Retorna (pontos, detalhes). Máximo: 30 pts."""
    detalhes: dict[str, Any] = {}

    # ── CNAE (0–10 pts) ──────────────────────────────────────────────
    pts_cnae = 0.0
    cnae = (firmografico.cnae_primario or "").replace(".", "").replace("-", "")[:4]
    cnaes_alta = [
        str(c).replace(".", "").replace("-", "")[:4]
        for c in calibragem.get("cnaes_alta_afinidade", [])
    ]
    cnaes_media = [
        str(c).replace(".", "").replace("-", "")[:4]
        for c in calibragem.get("cnaes_media_afinidade", [])
    ]
    if cnae and cnae in cnaes_alta:
        pts_cnae = 10.0
    elif cnae and cnae in cnaes_media:
        pts_cnae = 6.0
    elif cnae:
        # Verificar divisão (2 primeiros dígitos)
        div = cnae[:2]
        divs_alta = [c[:2] for c in cnaes_alta]
        divs_media = [c[:2] for c in cnaes_media]
        if div in divs_alta:
            pts_cnae = 7.0
        elif div in divs_media:
            pts_cnae = 4.0
        else:
            pts_cnae = 1.0   # CNAE presente mas sem afinidade mapeada
    detalhes["cnae"] = {"pontos": pts_cnae, "cnae_informado": cnae}

    # ── Faturamento (0–10 pts) ────────────────────────────────────────
    pts_fat = 0.0
    fat = firmografico.faturamento_estimado_brl
    fat_min = calibragem.get("faturamento_minimo_brl", 0)
    fat_ideal = calibragem.get("faturamento_ideal_brl", fat_min * 3 if fat_min else 0)
    fat_max = calibragem.get("faturamento_maximo_brl")  # None = sem limite superior

    if fat is not None and fat > 0:
        if fat < fat_min:
            pts_fat = 0.0   # abaixo do mínimo — pode ser desqualificador
        elif fat_max and fat > fat_max:
            pts_fat = 4.0   # acima do máximo ideal (overqualified)
        elif fat >= fat_ideal:
            pts_fat = 10.0
        else:
            # Interpolação linear entre mínimo e ideal
            pts_fat = 4.0 + 6.0 * (fat - fat_min) / max(fat_ideal - fat_min, 1)
    detalhes["faturamento"] = {
        "pontos": round(pts_fat, 1),
        "faturamento_informado": fat,
        "faturamento_minimo": fat_min,
        "faturamento_ideal": fat_ideal,
    }

    # ── Headcount (0–5 pts) ───────────────────────────────────────────
    pts_head = 0.0
    hc = firmografico.numero_funcionarios
    hc_min = calibragem.get("numero_funcionarios_minimo", 0)
    if hc is not None:
        if hc < hc_min:
            pts_head = 0.0
        elif hc >= 500:
            pts_head = 5.0
        elif hc >= 100:
            pts_head = 4.0
        elif hc >= 50:
            pts_head = 3.0
        elif hc >= 20:
            pts_head = 2.0
        else:
            pts_head = 1.0
    detalhes["headcount"] = {"pontos": pts_head, "funcionarios_informados": hc}

    # ── Região (0–5 pts) ──────────────────────────────────────────────
    pts_regiao = _REGIOES_SCORE.get(firmografico.estado or "", 2)
    detalhes["regiao"] = {"pontos": pts_regiao, "estado": firmografico.estado}

    total = pts_cnae + pts_fat + pts_head + pts_regiao
    return min(total, 30.0), detalhes


def _score_gatilhos(
    gatilhos_detectados: list[GatilhoDetectado],
    calibragem: dict,
) -> tuple[float, dict]:
    """Retorna (pontos, detalhes). Máximo: 50 pts."""
    pesos_calibragem: dict[str, float] = {
        g["id"]: g["peso"]
        for g in calibragem.get("gatilhos", [])
    }

    detalhes_gatilhos = []
    soma_ponderada = 0.0

    for g in gatilhos_detectados:
        if not g.presente:
            continue
        peso = pesos_calibragem.get(g.gatilho_id, 0.0)
        contribuicao = peso * g.confidence
        soma_ponderada += contribuicao
        detalhes_gatilhos.append({
            "gatilho_id": g.gatilho_id,
            "peso": peso,
            "confidence": g.confidence,
            "contribuicao": round(contribuicao, 4),
        })

    # Normalizar: soma máxima possível = 1.0 (todos os pesos somam 1.0 na calibragem)
    # Converter para 0–50 pts
    pts = min(soma_ponderada * 50.0, 50.0)

    detalhes = {
        "pontos": round(pts, 1),
        "soma_ponderada": round(soma_ponderada, 4),
        "gatilhos_contribuintes": detalhes_gatilhos,
    }
    return pts, detalhes


def _score_timing(
    gatilhos_detectados: list[GatilhoDetectado],
) -> tuple[float, dict]:
    """
    Timing baseado na data da evidência mais recente dentre os gatilhos presentes.
    Máximo: 20 pts.
    """
    datas_presentes = [
        g.data_evidencia
        for g in gatilhos_detectados
        if g.presente and g.data_evidencia is not None
    ]

    if not datas_presentes:
        # Nenhum gatilho tem data → timing incerto
        fator = 0.25
        descricao = "sem_data"
        dias_mais_recente = None
    else:
        data_mais_recente = max(datas_presentes)
        dias = _dias_desde(data_mais_recente)
        dias_mais_recente = dias

        if dias is not None and dias <= 30:
            fator = 1.0
            descricao = "ate_30_dias"
        elif dias is not None and dias <= 90:
            fator = 0.5
            descricao = "31_a_90_dias"
        else:
            fator = 0.25
            descricao = "mais_de_90_dias"

    pts = 20.0 * fator
    detalhes = {
        "pontos": round(pts, 1),
        "fator": fator,
        "categoria": descricao,
        "dias_evidencia_mais_recente": dias_mais_recente,
    }
    return pts, detalhes


def _calcular_bonus(
    firmografico: DadosFirmograficos,
) -> tuple[float, dict]:
    """Bônus independentes, cada um vale +5 pts. Total máximo: +15 pts."""
    bonus = 0.0
    detalhes = {}

    # Decisor postou no LinkedIn nos últimos 30 dias
    post_dias = firmografico.decisor_linkedin_post_dias
    if post_dias is not None and post_dias <= 30:
        bonus += 5.0
        detalhes["decisor_ativo_linkedin"] = True
    else:
        detalhes["decisor_ativo_linkedin"] = False

    # Headcount cresceu > 20% (comparando com headcount_anterior)
    hc_atual = firmografico.numero_funcionarios
    hc_ant = firmografico.headcount_anterior
    if hc_atual and hc_ant and hc_ant > 0:
        crescimento = (hc_atual - hc_ant) / hc_ant
        if crescimento > 0.20:
            bonus += 5.0
            detalhes["crescimento_headcount"] = round(crescimento * 100, 1)
        else:
            detalhes["crescimento_headcount"] = None
    else:
        detalhes["crescimento_headcount"] = None

    # Decisor novo no cargo (≤ 90 dias)
    cargo_dias = firmografico.decisor_novo_cargo_dias
    if cargo_dias is not None and cargo_dias <= 90:
        bonus += 5.0
        detalhes["decisor_novo_cargo"] = True
    else:
        detalhes["decisor_novo_cargo"] = False

    return bonus, {"pontos": bonus, "itens": detalhes}


# ─────────────────────────────────────────
# VERIFICAÇÃO DE DESQUALIFICADORES
# ─────────────────────────────────────────

def _verificar_desqualificadores(
    firmografico: DadosFirmograficos,
    calibragem: dict,
) -> tuple[bool, str | None]:
    """
    Retorna (desqualificado, razao).
    Se desqualificado = True, o score final deve ser 0.
    """
    desq = calibragem.get("criterios_desqualificadores", [])

    fat = firmografico.faturamento_estimado_brl
    fat_min = calibragem.get("faturamento_minimo_brl")
    fat_max = calibragem.get("faturamento_maximo_brl")
    hc = firmografico.numero_funcionarios
    hc_min = calibragem.get("numero_funcionarios_minimo")

    for criterio in desq:
        tipo = criterio.get("tipo")

        if tipo == "faturamento_abaixo_minimo":
            if fat is not None and fat_min is not None and fat < fat_min:
                return True, f"Faturamento R${fat:,.0f} abaixo do mínimo R${fat_min:,.0f}"

        elif tipo == "faturamento_acima_maximo":
            if fat is not None and fat_max is not None and fat > fat_max:
                return True, f"Faturamento R${fat:,.0f} acima do máximo R${fat_max:,.0f}"

        elif tipo == "headcount_abaixo_minimo":
            if hc is not None and hc_min is not None and hc < hc_min:
                return True, f"Headcount {hc} abaixo do mínimo {hc_min}"

        elif tipo == "setor_excluido":
            cnaes_excluidos = criterio.get("cnaes", [])
            cnae = (firmografico.cnae_primario or "").replace(".", "")[:4]
            for exc in cnaes_excluidos:
                exc_norm = str(exc).replace(".", "")[:4]
                if cnae.startswith(exc_norm):
                    return True, f"CNAE {cnae} pertence a setor excluído ({exc})"

        elif tipo == "campo_obrigatorio_ausente":
            campo = criterio.get("campo")
            if campo == "exportacao_ativa":
                # Verificado externamente — passado como flag no calibragem ou contexto
                pass  # tratado pelo chamador via criterios_obrigatorios_externos

    return False, None


# ─────────────────────────────────────────
# FUNÇÃO PRINCIPAL
# ─────────────────────────────────────────

def calcular_score(
    firmografico: DadosFirmograficos,
    gatilhos_detectados: list[GatilhoDetectado],
    calibragem: dict,
    criterios_externos: dict | None = None,
) -> ResultadoScore:
    """
    Calcula o score de fit e urgência de uma empresa para um produto.

    Args:
        firmografico: dados da empresa (CNAE, faturamento, headcount, região, etc.)
        gatilhos_detectados: lista de GatilhoDetectado gerados pelo Prompt A
        calibragem: dicionário carregado do YAML de calibragem do produto
        criterios_externos: flags booleanos para critérios que não podem ser
                            derivados dos dados firmográficos (ex: exportacao_ativa)

    Returns:
        ResultadoScore com score_total, classificacao e detalhes por componente
    """
    criterios_externos = criterios_externos or {}

    # ── Desqualificadores ────────────────────────────────────────────
    desq, razao_desq = _verificar_desqualificadores(firmografico, calibragem)

    # Verificar critérios obrigatórios externos
    for criterio in calibragem.get("criterios_obrigatorios_externos", []):
        campo = criterio.get("campo")
        if campo and not criterios_externos.get(campo, False):
            desq = True
            razao_desq = criterio.get("razao", f"Critério obrigatório ausente: {campo}")
            break

    if desq:
        return ResultadoScore(
            score_total=0.0,
            classificacao="C",
            detalhes={"desqualificacao": razao_desq},
            desqualificado=True,
            razao_desqualificacao=razao_desq,
        )

    # ── Componentes ──────────────────────────────────────────────────
    pts_firm, det_firm = _score_firmografico(firmografico, calibragem)
    pts_gat, det_gat = _score_gatilhos(gatilhos_detectados, calibragem)
    pts_tim, det_tim = _score_timing(gatilhos_detectados)
    pts_bonus, det_bonus = _calcular_bonus(firmografico)

    # ── Score final ──────────────────────────────────────────────────
    score_bruto = pts_firm + pts_gat + pts_tim + pts_bonus
    score_final = min(score_bruto, 100.0)

    # ── Classificação ─────────────────────────────────────────────────
    if score_final >= 80:
        classificacao = "A"
    elif score_final >= 60:
        classificacao = "B"
    else:
        classificacao = "C"

    detalhes = {
        "firmografico": {**det_firm, "pontos_total": round(pts_firm, 1)},
        "gatilhos": {**det_gat, "pontos_total": round(pts_gat, 1)},
        "timing": {**det_tim, "pontos_total": round(pts_tim, 1)},
        "bonus": {**det_bonus},
        "score_bruto": round(score_bruto, 1),
        "score_final": round(score_final, 1),
        "produto": calibragem.get("produto", "desconhecido"),
        "calibragem_versao": calibragem.get("versao", "desconhecida"),
    }

    return ResultadoScore(
        score_total=score_final,
        classificacao=classificacao,
        detalhes=detalhes,
    )


# ─────────────────────────────────────────
# AÇÃO SUGERIDA
# ─────────────────────────────────────────

def acao_sugerida(score: float) -> str:
    if score >= 80:
        return "abordar_agora"
    elif score >= 60:
        return "abordar_breve"
    elif score >= 20:
        return "monitorar"
    else:
        return "descartar"


# ─────────────────────────────────────────
# CLI DE TESTE
# ─────────────────────────────────────────

if __name__ == "__main__":
    import yaml, pathlib, json

    calibragem_path = pathlib.Path("shared/calibracoes/cambio_spot_v1.yaml")
    with open(calibragem_path, encoding="utf-8") as f:
        calibragem = yaml.safe_load(f)

    firma = DadosFirmograficos(
        cnae_primario="4693",
        faturamento_estimado_brl=35_000_000,
        numero_funcionarios=80,
        estado="SP",
        decisor_linkedin_post_dias=15,
        decisor_novo_cargo_dias=45,
    )

    gatilhos = [
        GatilhoDetectado("internacionalizacao_ativa", True, 0.85, "2025-04-20"),
        GatilhoDetectado("crescimento_receita_acelerado", True, 0.70, "2025-03-10"),
        GatilhoDetectado("captacao_venture_pe", False, 0.0, None),
        GatilhoDetectado("setor_alta_afinidade_cambio", True, 0.90, "2025-04-01"),
        GatilhoDetectado("contratacao_executivo_financeiro", False, 0.0, None),
    ]

    resultado = calcular_score(firma, gatilhos, calibragem)
    print(json.dumps(resultado.to_dict(), ensure_ascii=False, indent=2))
    print(f"\nAção sugerida: {acao_sugerida(resultado.score_total)}")

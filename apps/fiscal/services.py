"""
Regras do módulo Fiscal. Emite documento pelo gateway ativo e registra o retorno.
A natureza decide o tipo: SERVIÇO → NFS-e; CONSUMO → NFC-e. Interface pública para
os outros módulos emitirem a partir de uma conta/venda/comanda (a ligar na fase 2).
"""
from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from apps.nucleo.models import NaturezaFiscal, modulo_ativo, registrar_auditoria
from apps.nucleo.modulos import Modulo

from .gateways import get_gateway
from .models import DocumentoFiscal, EventoFiscal


def _tipo_por_natureza(natureza):
    return (DocumentoFiscal.Tipo.NFSE if natureza == NaturezaFiscal.SERVICO
            else DocumentoFiscal.Tipo.NFCE)


@transaction.atomic
def emitir(operador, *, natureza, valor, descricao, tomador=None, referencia=""):
    """Cria e emite um documento fiscal pelo gateway ativo (idempotência por origem
    fica para a fase 2). Retorna o DocumentoFiscal com o status do fisco."""
    valor = Decimal(str(valor or 0))
    if valor <= 0:
        raise ValidationError("Valor do documento deve ser positivo.")
    if natureza not in (NaturezaFiscal.SERVICO, NaturezaFiscal.CONSUMO):
        raise ValidationError("Natureza fiscal inválida.")

    doc = DocumentoFiscal.objects.create(
        tipo=_tipo_por_natureza(natureza), natureza=natureza,
        descricao=descricao, valor=valor, tomador=tomador,
        referencia=referencia, criado_por=operador,
        status=DocumentoFiscal.Status.PROCESSANDO,
    )
    EventoFiscal.objects.create(documento=doc, tipo="emissao",
                                detalhe={"gateway": getattr(get_gateway(), "nome", "")})

    resultado = get_gateway().emitir(doc)  # pode levantar NotImplementedError nos stubs
    for campo in ("gateway", "gateway_id", "numero", "serie", "chave",
                  "protocolo", "xml_url", "pdf_url", "payload"):
        if campo in resultado:
            setattr(doc, campo, resultado[campo])
    estado = resultado.get("status")
    if estado == "autorizada":
        doc.status = DocumentoFiscal.Status.AUTORIZADA
        doc.autorizada_em = timezone.now()
        EventoFiscal.objects.create(documento=doc, tipo="autorizada")
    elif estado in ("processando", "pendente", "enviada"):
        # Emissão assíncrona (ex.: Spedy): aceita pelo gateway, aguarda o webhook
        # para autorizar/rejeitar. Fica PROCESSANDO (status já setado na criação).
        doc.status = DocumentoFiscal.Status.PROCESSANDO
        EventoFiscal.objects.create(documento=doc, tipo="enviada",
                                    detalhe={"gateway_id": resultado.get("gateway_id", "")})
    else:
        doc.status = DocumentoFiscal.Status.REJEITADA
        doc.motivo_rejeicao = resultado.get("motivo_rejeicao", "")[:255]
        EventoFiscal.objects.create(documento=doc, tipo="rejeitada",
                                    detalhe={"motivo": doc.motivo_rejeicao})
    doc.save()
    return doc


@transaction.atomic
def cancelar(documento, operador, motivo):
    if documento.status != DocumentoFiscal.Status.AUTORIZADA:
        raise ValidationError("Só documentos autorizados podem ser cancelados.")
    resultado = get_gateway().cancelar(documento, motivo)
    documento.status = DocumentoFiscal.Status.CANCELADA
    documento.motivo_rejeicao = motivo[:255]
    documento.save(update_fields=["status", "motivo_rejeicao"])
    EventoFiscal.objects.create(documento=documento, tipo="cancelada", detalhe=resultado)
    registrar_auditoria(operador, "cancelamento_fiscal", documento, {"motivo": motivo})
    return documento


# ── Fluxo NFS-e da hospedagem (diária) — ESBOÇO ───────────────────────────────

@transaction.atomic
def emitir_nfse_da_conta(conta_id, operador):
    """Emite a NFS-e da hospedagem a partir da conta do quarto (parte SERVIÇO).
    Idempotente por conta. Usa os parâmetros confirmados pelo contador
    (código 090101, ISS 4%, regime Lucro Presumido — settings). NFC-e do consumo
    fica para quando a Inscrição Estadual sair."""
    if not modulo_ativo(Modulo.RESERVAS):
        raise ValidationError("Módulo Reservas inativo.")
    # Serializa a emissão por conta: sem o lock, duplo clique/concorrência passa os dois
    # pelo check de idempotência e cria duas NFS-e para a mesma hospedagem.
    from apps.reservas.models import ContaHospedagem
    ContaHospedagem.objects.select_for_update().filter(pk=conta_id).first()
    from apps.reservas.services import resumo_fiscal_conta
    resumo = resumo_fiscal_conta(conta_id)
    if not resumo:
        raise ValidationError("Conta não encontrada.")
    if resumo["servico"] <= 0:
        raise ValidationError("Não há valor de hospedagem (serviço) para emitir NFS-e.")

    ref = f"conta:{conta_id}"
    existente = (
        DocumentoFiscal.objects
        .filter(referencia=ref, tipo=DocumentoFiscal.Tipo.NFSE)
        .exclude(status=DocumentoFiscal.Status.CANCELADA)
        .first()
    )
    if existente:
        return existente  # já emitida — não duplica

    doc = emitir(
        operador, natureza=NaturezaFiscal.SERVICO, valor=resumo["servico"],
        descricao=f"Hospedagem em hotelaria — {resumo['uh']}",
        tomador=resumo["hospede"], referencia=ref,
    )
    # Anexa os parâmetros da NFS-e (o gateway real — Focus — usa na montagem).
    doc.payload = {
        **doc.payload,
        "codigo_servico": settings.FISCAL_NFSE_CODIGO_SERVICO,   # 090101 hospedagem
        "iss_aliquota": settings.FISCAL_NFSE_ISS_ALIQUOTA,       # 4% Itá
        "regime": settings.FISCAL_REGIME,                         # lucro_presumido
    }
    doc.save(update_fields=["payload"])
    return doc


@transaction.atomic
def processar_retorno_focus(payload: dict):
    """Processa o webhook do Focus NFe (NFS-e/NF-e assíncronas): acha o documento
    pela `ref` e atualiza status + PDF (DANFSE/DANFE) + XML. Idempotente."""
    ref = payload.get("ref")
    doc = DocumentoFiscal.objects.filter(gateway_id=ref).first() if ref else None
    if not doc:
        return None
    status = (payload.get("status") or "").lower()
    # CANCELADA é terminal: um retorno fora de ordem (retry/fila) não pode "ressuscitar"
    # a nota de volta para autorizada.
    if doc.status == DocumentoFiscal.Status.CANCELADA:
        EventoFiscal.objects.create(documento=doc, tipo="webhook_ignorado",
                                    detalhe={"status": status, "atual": "cancelada"})
        return doc
    # Status intermediário/desconhecido: não sobrescreve número/chave definitivos nem
    # salva — só registra um evento informativo (evita corromper a nota por um retorno
    # que não casa nenhum ramo).
    if status not in ("autorizado", "autorizada", "cancelado", "cancelada") \
            and not status.startswith("erro"):
        EventoFiscal.objects.create(documento=doc, tipo="webhook_info",
                                    detalhe={"status": status, "origem": "webhook"})
        return doc
    doc.numero = str(payload.get("numero", doc.numero) or doc.numero)
    doc.chave = payload.get("codigo_verificacao") or payload.get("chave_nfe") or doc.chave
    doc.pdf_url = payload.get("url_danfse") or payload.get("url") or doc.pdf_url
    doc.xml_url = payload.get("caminho_xml_nota_fiscal") or doc.xml_url
    doc.payload = {**doc.payload, "webhook": payload}
    if status in ("autorizado", "autorizada"):
        doc.status = DocumentoFiscal.Status.AUTORIZADA
        doc.autorizada_em = timezone.now()
        EventoFiscal.objects.create(documento=doc, tipo="autorizada",
                                    detalhe={"origem": "webhook"})
    elif status in ("cancelado", "cancelada"):
        doc.status = DocumentoFiscal.Status.CANCELADA
        EventoFiscal.objects.create(documento=doc, tipo="cancelada",
                                    detalhe={"origem": "webhook"})
    elif status.startswith("erro"):
        doc.status = DocumentoFiscal.Status.REJEITADA
        doc.motivo_rejeicao = str(
            payload.get("mensagem_sefaz") or payload.get("erros") or "Rejeitada"
        )[:255]
        EventoFiscal.objects.create(documento=doc, tipo="rejeitada",
                                    detalhe={"origem": "webhook"})
    doc.save()
    return doc


@transaction.atomic
def processar_retorno_spedy(payload: dict):
    """
    Webhook do Spedy (`invoice.status_changed`/`invoice.authorized`/`invoice.rejected`).
    Acha o documento por `integrationId` (= referencia) ou pelo `id` do gateway, e atualiza
    status + número/chave/XML/PDF. Idempotente; cancelada é terminal (não ressuscita).
    """
    # O payload pode vir achatado ou dentro de "data"/"invoice".
    dados = payload.get("data") or payload.get("invoice") or payload
    integration_id = dados.get("integrationId") or payload.get("integrationId")
    gw_id = str(dados.get("id") or payload.get("id") or "")

    doc = None
    if integration_id:
        doc = DocumentoFiscal.objects.filter(referencia=integration_id).first()
    if not doc and gw_id:
        doc = DocumentoFiscal.objects.filter(gateway_id=gw_id).first()
    if not doc:
        return None

    if doc.status == DocumentoFiscal.Status.CANCELADA:
        EventoFiscal.objects.create(documento=doc, tipo="webhook_ignorado",
                                    detalhe={"atual": "cancelada"})
        return doc

    status = (dados.get("status") or payload.get("status") or "").lower()
    doc.payload = {**doc.payload, "webhook_spedy": payload}

    if status == "authorized":
        doc.numero = str(dados.get("number") or doc.numero or "")
        doc.chave = dados.get("accessKey") or dados.get("verificationCode") or doc.chave
        doc.pdf_url = dados.get("pdfUrl") or dados.get("pdf") or doc.pdf_url
        doc.xml_url = dados.get("xmlUrl") or dados.get("xml") or doc.xml_url
        doc.status = DocumentoFiscal.Status.AUTORIZADA
        doc.autorizada_em = timezone.now()
        EventoFiscal.objects.create(documento=doc, tipo="autorizada", detalhe={"origem": "spedy"})
    elif status == "rejected":
        doc.status = DocumentoFiscal.Status.REJEITADA
        doc.motivo_rejeicao = str(dados.get("rejectionReason") or dados.get("message") or "Rejeitada")[:255]
        EventoFiscal.objects.create(documento=doc, tipo="rejeitada", detalhe={"origem": "spedy"})
    elif status in ("canceled", "cancelled"):
        doc.status = DocumentoFiscal.Status.CANCELADA
        EventoFiscal.objects.create(documento=doc, tipo="cancelada", detalhe={"origem": "spedy"})
    else:
        # created/enqueued/received/inContingent → só registra, não muda o status final
        EventoFiscal.objects.create(documento=doc, tipo="webhook_info",
                                    detalhe={"status": status, "origem": "spedy"})
    doc.save()
    return doc


def pendencias_auditoria():
    """Documentos fiscais rejeitados para a Auditoria (read-only)."""
    from django.urls import reverse
    achados = []
    for d in DocumentoFiscal.objects.filter(status=DocumentoFiscal.Status.REJEITADA):
        achados.append({
            "area": "Fiscal", "tipo": "nota_rejeitada", "gravidade": "alta",
            "descricao": f"{d.get_tipo_display()} #{d.pk} rejeitada: {d.motivo_rejeicao or 'sem motivo'}.",
            "url": reverse("fiscal:detalhe", args=[d.pk]),
        })
    return achados


# ── Demais integrações (fase 2) ───────────────────────────────────────────────
# emitir_nfce_da_venda/comanda(...): NFC-e do PDV — depende da Inscrição Estadual + CSC.
# Ver docs/Implementar_fiscal.md e docs/Produtos_para_NCM.md.

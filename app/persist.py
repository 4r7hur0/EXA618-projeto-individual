from app.models import Aparelho, OfertaMercado
from app.preco_util import normalizar_termo_cache


def _coerce_crawler_dict(d) -> dict | None:
    """Crawler às vezes devolve [dict]; APIs antigas podem ainda passar lista."""
    if d is None:
        return None
    if isinstance(d, dict):
        return d
    if isinstance(d, list):
        for x in d:
            if isinstance(x, dict):
                return x
    return None


def aparelho_from_mais_celular(termo_busca: str, d: dict) -> Aparelho:
    d = _coerce_crawler_dict(d)
    if not d:
        raise TypeError("Ficha Mais Celular inválida: esperado um objeto (dict), não lista.")
    esp = d.get("especificacoes_todas")
    if isinstance(esp, dict):
        esp_json = dict(esp)
    else:
        esp_json = None
    t = termo_busca.strip()[:512]
    return Aparelho(
        termo_busca=t,
        termo_normalizado=normalizar_termo_cache(t)[:512],
        modelo=(d.get("modelo") or "")[:512],
        url_fonte=d.get("url"),
        imagem_url=d.get("imagem_url"),
        antutu=d.get("antutu"),
        geekbench=d.get("geekbench"),
        processador=d.get("processador"),
        sistema_operacional=d.get("sistema_operacional"),
        memoria_ram=d.get("memoria_ram"),
        armazenamento=d.get("armazenamento"),
        tela=d.get("tela"),
        camera_traseira=d.get("camera_traseira"),
        camera_frontal=d.get("camera_frontal"),
        conectividade=d.get("conectividade"),
        bateria=d.get("bateria"),
        carregamento=d.get("carregamento"),
        dimensoes=d.get("dimensoes"),
        peso=d.get("peso"),
        audio=d.get("audio"),
        biometria=d.get("biometria"),
        especificacoes_json=esp_json,
        extraido_em_texto=d.get("data"),
    )


def oferta_from_amazon(termo_busca: str, d: dict) -> OfertaMercado:
    d = _coerce_crawler_dict(d)
    if not d:
        raise TypeError("Oferta Amazon inválida: esperado dict.")
    t = termo_busca.strip()[:512]
    return OfertaMercado(
        origem="amazon",
        termo_busca=t,
        termo_normalizado=normalizar_termo_cache(t)[:512],
        nome_produto=d.get("nome") or "",
        memoria=d.get("memoria"),
        preco=d.get("preco"),
        link=d.get("link"),
        imagem_url=d.get("imagem_url"),
        extraido_em_texto=d.get("data_extracao"),
    )


def oferta_from_mercadolivre(termo_busca: str, d: dict) -> OfertaMercado:
    d = _coerce_crawler_dict(d)
    if not d:
        raise TypeError("Oferta Mercado Livre inválida: esperado dict.")
    t = termo_busca.strip()[:512]
    return OfertaMercado(
        origem="mercadolivre",
        termo_busca=t,
        termo_normalizado=normalizar_termo_cache(t)[:512],
        nome_produto=d.get("nome") or "",
        memoria=d.get("memoria"),
        preco=d.get("preco"),
        link=d.get("link"),
        imagem_url=d.get("imagem_url"),
        vendedor=d.get("vendedor"),
        reputacao=d.get("reputacao"),
        reputacao_nivel=d.get("reputacao_nivel"),
        vendas_aprox=d.get("vendas_aprox"),
        extraido_em_texto=d.get("data"),
    )

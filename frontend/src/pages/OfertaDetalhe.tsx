import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { EspecificacoesAparelho } from "../components/EspecificacoesAparelho";
import type { OfertaDetalhe } from "../api";
import { getOferta } from "../api";

export function OfertaDetalhePage() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const oid = id ? parseInt(id, 10) : NaN;
  const [o, setO] = useState<OfertaDetalhe | null>(null);
  const [erro, setErro] = useState<string | null>(null);

  useEffect(() => {
    if (Number.isNaN(oid)) return;
    getOferta(oid)
      .then(setO)
      .catch((e) => setErro(e instanceof Error ? e.message : "Erro"));
  }, [oid]);

  if (Number.isNaN(oid)) {
    return <div className="alert alert-warning">ID inválido.</div>;
  }

  if (erro) {
    return (
      <>
        <div className="alert alert-warning">{erro}</div>
        <button type="button" className="btn btn-outline-secondary" onClick={() => navigate(-1)}>
          &larr; Voltar
        </button>
      </>
    );
  }

  if (!o) {
    return (
      <div className="text-center py-5">
        <div className="spinner-border text-primary" />
      </div>
    );
  }

  return (
    <>
      <div className="mb-3">
        <button type="button" className="btn btn-outline-secondary" onClick={() => navigate(-1)}>
          &larr; Voltar
        </button>
      </div>

      <h1 className="h4 mb-3">{o.nome_produto}</h1>

      <p>
        <span className="badge bg-secondary">{o.origem}</span>
      </p>
      <p className="text-muted small">
        Busca: {o.termo_busca} · Extraído: {o.extraido_em_texto || "—"} · Salvo em:{" "}
        {o.criado_em
          ? new Date(o.criado_em).toLocaleString("pt-BR", { timeZone: "UTC" }) + " UTC"
          : "—"}
      </p>

      {o.imagem_url ? (
        <div className="text-center mb-3">
          <img
            src={o.imagem_url}
            alt={o.nome_produto}
            className="img-fluid rounded border shadow-sm"
            style={{ maxHeight: 260, objectFit: "contain" }}
            loading="lazy"
            referrerPolicy="no-referrer"
          />
        </div>
      ) : null}

      <div className="card p-4 mb-3">
        <p className="mb-1">
          <strong>Preço:</strong> {o.preco || "—"}
        </p>
        <p className="mb-1">
          <strong>Memória:</strong> {o.memoria || "—"}
        </p>
        {o.link ? (
          <p className="mb-0">
            <a href={o.link} target="_blank" rel="noopener noreferrer">
              Abrir anúncio
            </a>
          </p>
        ) : null}
      </div>

      {o.origem === "mercadolivre" ? (
        <div className="card p-4 mb-3">
          <p className="mb-1">
            <strong>Vendedor:</strong> {o.vendedor || "—"}
          </p>
          <p className="mb-1">
            <strong>Reputação:</strong> {o.reputacao || "—"}
          </p>
          {o.reputacao_nivel ? (
            <p className="mb-1">
              <strong>Nível:</strong> {o.reputacao_nivel}
            </p>
          ) : null}
          {o.vendas_aprox ? (
            <p className="mb-0">
              <strong>Vendas:</strong> {o.vendas_aprox}
            </p>
          ) : null}
        </div>
      ) : null}

      {o.aparelho ? (
        <EspecificacoesAparelho aparelho={o.aparelho} />
      ) : o.aparelho_id ? (
        <div className="alert alert-light border mt-4">
          Esta oferta está vinculada a um aparelho, mas a ficha técnica não foi carregada.
        </div>
      ) : null}
    </>
  );
}

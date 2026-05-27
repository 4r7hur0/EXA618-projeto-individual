import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { EspecificacoesAparelho } from "../components/EspecificacoesAparelho";
import type { AparelhoDetalhe } from "../api";
import { excluirAparelho, getAparelho } from "../api";

function str(v: unknown): string {
  if (v == null) return "—";
  return String(v);
}

export function AparelhoDetalhePage() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const apId = id ? parseInt(id, 10) : NaN;
  const [a, setA] = useState<AparelhoDetalhe | null>(null);
  const [erro, setErro] = useState<string | null>(null);

  useEffect(() => {
    if (Number.isNaN(apId)) return;
    getAparelho(apId)
      .then(setA)
      .catch((e) => setErro(e instanceof Error ? e.message : "Erro"));
  }, [apId]);

  async function onExcluir() {
    if (!a || !window.confirm("Excluir esta ficha?")) return;
    try {
      await excluirAparelho(a.id);
      navigate("/");
    } catch (e) {
      alert(e instanceof Error ? e.message : "Falha ao excluir");
    }
  }

  if (Number.isNaN(apId)) {
    return <div className="alert alert-warning">ID inválido.</div>;
  }

  if (erro) {
    return (
      <>
        <div className="alert alert-warning">{erro}</div>
        <button type="button" className="btn btn-outline-secondary" onClick={() => navigate("/")}>
          &larr; Voltar
        </button>
      </>
    );
  }

  if (!a) {
    return (
      <div className="text-center py-5">
        <div className="spinner-border text-primary" />
      </div>
    );
  }

  const modelo = str(a.modelo);

  return (
    <>
      <div className="mb-3">
        <button type="button" className="btn btn-outline-secondary" onClick={() => navigate("/")}>
          &larr; Voltar
        </button>
      </div>

      <div className="d-flex justify-content-between align-items-start flex-wrap gap-2 mb-3">
        <h1 className="h3">{modelo}</h1>
        <button type="button" className="btn btn-outline-danger btn-sm" onClick={onExcluir}>
          Excluir
        </button>
      </div>

      <p className="text-muted small">
        Busca: {str(a.termo_busca)} · Extraído: {str(a.data)} · Salvo em:{" "}
        {a.criado_em
          ? new Date(String(a.criado_em)).toLocaleString("pt-BR", { timeZone: "UTC" }) + " UTC"
          : "—"}
      </p>

      {a.imagem_url ? (
        <div className="mb-4 text-center">
          <img
            src={String(a.imagem_url)}
            alt={modelo}
            className="img-fluid rounded border shadow-sm"
            style={{ maxHeight: 280, objectFit: "contain" }}
            loading="lazy"
            referrerPolicy="no-referrer"
          />
        </div>
      ) : null}

      {a.url ? (
        <p>
          <a href={String(a.url)} target="_blank" rel="noopener noreferrer">
            Abrir fonte (Mais Celular)
          </a>
        </p>
      ) : null}

      <EspecificacoesAparelho aparelho={a} titulo="Especificações" />
    </>
  );
}

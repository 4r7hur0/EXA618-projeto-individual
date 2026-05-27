import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import type { OfertaLista } from "../api";
import { listarOfertas } from "../api";

export function OfertasLista() {
  const [items, setItems] = useState<OfertaLista[]>([]);
  const [erro, setErro] = useState<string | null>(null);

  useEffect(() => {
    listarOfertas()
      .then((r) => setItems(r.items))
      .catch((e) => setErro(e instanceof Error ? e.message : "Erro ao carregar"));
  }, []);

  function fmtData(iso: string | null) {
    if (!iso) return "—";
    try {
      return new Date(iso).toLocaleString("pt-BR");
    } catch {
      return iso;
    }
  }

  return (
    <>
      <h1 className="h3 mb-4">Ofertas (Amazon / Mercado Livre)</h1>
      {erro ? <div className="alert alert-danger">{erro}</div> : null}
      <div className="table-responsive">
        <table className="table table-hover bg-white shadow-sm">
          <thead>
            <tr>
              <th>ID</th>
              <th>Origem</th>
              <th>Produto</th>
              <th>Preço</th>
              <th>Extraído em</th>
              <th>Salvo em</th>
            </tr>
          </thead>
          <tbody>
            {items.length === 0 && !erro ? (
              <tr>
                <td colSpan={6} className="text-muted">
                  Nenhum registro.
                </td>
              </tr>
            ) : (
              items.map((o) => (
                <tr key={o.id}>
                  <td>{o.id}</td>
                  <td>
                    <span className="badge bg-secondary">{o.origem}</span>
                  </td>
                  <td>
                    <Link to={`/ofertas/${o.id}`}>
                      {o.nome_produto.length > 80 ? o.nome_produto.slice(0, 80) + "…" : o.nome_produto}
                    </Link>
                  </td>
                  <td>{o.preco || "—"}</td>
                  <td>{o.extraido_em_texto || "—"}</td>
                  <td>{fmtData(o.criado_em)}</td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
    </>
  );
}

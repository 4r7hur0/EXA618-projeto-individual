import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import type { AparelhoLista } from "../api";
import { listarAparelhos } from "../api";

export function AparelhosLista() {
  const [items, setItems] = useState<AparelhoLista[]>([]);
  const [erro, setErro] = useState<string | null>(null);

  useEffect(() => {
    listarAparelhos()
      .then((r) => setItems(r.items))
      .catch((e) => setErro(e instanceof Error ? e.message : "Erro ao carregar"));
  }, []);

  function fmtData(iso: string | null) {
    if (!iso) return "—";
    try {
      const d = new Date(iso);
      return d.toLocaleString("pt-BR");
    } catch {
      return iso;
    }
  }

  return (
    <>
      <h1 className="h3 mb-4">Fichas técnicas salvas</h1>
      {erro ? <div className="alert alert-danger">{erro}</div> : null}
      <div className="table-responsive">
        <table className="table table-hover bg-white shadow-sm">
          <thead>
            <tr>
              <th>ID</th>
              <th>Modelo</th>
              <th>Busca</th>
              <th>Extraído em</th>
              <th>Salvo em</th>
            </tr>
          </thead>
          <tbody>
            {items.length === 0 && !erro ? (
              <tr>
                <td colSpan={5} className="text-muted">
                  Nenhum registro.
                </td>
              </tr>
            ) : (
              items.map((a) => (
                <tr key={a.id}>
                  <td>{a.id}</td>
                  <td>
                    <Link to={`/aparelhos/${a.id}`}>{a.modelo}</Link>
                  </td>
                  <td>{a.termo_busca}</td>
                  <td>{a.extraido_em_texto || "—"}</td>
                  <td>{fmtData(a.criado_em)}</td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
    </>
  );
}

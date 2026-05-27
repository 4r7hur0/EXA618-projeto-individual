import { FormEvent, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { buscarNoBanco } from "../api";

export function Home() {
  const navigate = useNavigate();
  const [termo, setTermo] = useState("");
  const [erro, setErro] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setErro(null);
    const t = termo.trim();
    if (!t) {
      setErro("Informe o modelo ou termo de busca.");
      return;
    }
    setLoading(true);
    try {
      await buscarNoBanco(t);
      navigate(`/resultado/${encodeURIComponent(t)}`);
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Falha na busca.";
      setErro(msg.includes("404") || msg.includes("base") ? "Este aparelho não está na base de dados." : msg);
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="row justify-content-center">
      <div className="col-lg-8">
        <h1 className="h3 mb-2 text-center">Buscar aparelho</h1>
        <p className="text-center text-muted mb-4">
          Cadastro salvo por modelo. Para filtrar por preço, loja e armazenamento, use{" "}
          <Link to="/explorar">Explorar ofertas</Link>.
        </p>

        {erro ? <div className="alert alert-danger">{erro}</div> : null}

        <div className="card shadow-sm">
          <div className="card-body p-4">
            <form onSubmit={onSubmit} className="position-relative">
              <div className="mb-3">
                <label className="form-label visually-hidden" htmlFor="q">
                  Modelo
                </label>
                <input
                  className="form-control form-control-lg"
                  id="q"
                  value={termo}
                  onChange={(e) => setTermo(e.target.value)}
                  placeholder="Ex.: iPhone 16 128Gb"
                  required
                  autoComplete="off"
                  autoFocus
                  disabled={loading}
                />
              </div>
              <button type="submit" className="btn btn-primary btn-lg w-100" disabled={loading}>
                {loading ? "Buscando…" : "Buscar"}
              </button>
              {loading ? (
                <div className="text-center py-4 mt-3 border-top">
                  <div className="spinner-border text-primary" role="status">
                    <span className="visually-hidden">Carregando…</span>
                  </div>
                  <p className="text-muted small mt-2 mb-0">Consultando a base de dados…</p>
                </div>
              ) : null}
            </form>
          </div>
        </div>
      </div>
    </div>
  );
}

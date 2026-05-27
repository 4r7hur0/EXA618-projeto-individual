import { FormEvent, useState } from "react";
import { Link } from "react-router-dom";
import type { OfertaFiltrada, OfertasFiltrosRequest } from "../api";
import { filtrarOfertas } from "../api";

const ARMAZENAMENTOS = [
  { value: "", label: "Qualquer" },
  { value: "64", label: "64 GB" },
  { value: "128", label: "128 GB" },
  { value: "256", label: "256 GB" },
  { value: "512", label: "512 GB" },
  { value: "1024", label: "1 TB" },
] as const;

function origemLabel(origem: string) {
  if (origem === "amazon") return "Amazon";
  if (origem === "mercadolivre") return "Mercado Livre";
  return origem;
}

function origemBadgeClass(origem: string) {
  if (origem === "amazon") return "bg-warning text-dark";
  if (origem === "mercadolivre") return "bg-success";
  return "bg-secondary";
}

function OfertaCard({ o }: { o: OfertaFiltrada }) {
  const mem =
    o.rotulo_memoria ||
    (o.armazenamento_gb ? `${o.armazenamento_gb} GB` : null) ||
    o.memoria;

  return (
    <div className="col-md-6 col-lg-4">
      <div className="card h-100 shadow-sm">
        {o.imagem_url ? (
          <div className="card-img-top p-3 text-center bg-light" style={{ minHeight: 140 }}>
            <img
              src={o.imagem_url}
              alt=""
              className="img-fluid"
              style={{ maxHeight: 120, objectFit: "contain" }}
              loading="lazy"
              referrerPolicy="no-referrer"
            />
          </div>
        ) : null}
        <div className="card-body d-flex flex-column">
          <div className="mb-2">
            <span className={`badge ${origemBadgeClass(o.origem)}`}>{origemLabel(o.origem)}</span>
            {mem ? (
              <span className="badge bg-light text-dark border ms-1">{mem}</span>
            ) : null}
          </div>
          <h2 className="h6 card-title flex-grow-1">
            <Link to={`/ofertas/${o.id}`} className="text-decoration-none text-dark">
              {o.nome.length > 90 ? o.nome.slice(0, 90) + "…" : o.nome}
            </Link>
          </h2>
          {o.aparelho?.modelo ? (
            <p className="small text-muted mb-2">Modelo: {o.aparelho.modelo}</p>
          ) : null}
          <p className="fs-5 fw-semibold text-primary mb-3">{o.preco || "Preço não informado"}</p>
          <div className="mt-auto d-grid gap-2">
            <Link to={`/ofertas/${o.id}`} className="btn btn-outline-primary btn-sm">
              Ver detalhes
            </Link>
            {o.link ? (
              <a
                href={o.link}
                target="_blank"
                rel="noopener noreferrer"
                className={
                  o.origem === "amazon"
                    ? "btn btn-warning btn-sm text-dark"
                    : "btn btn-success btn-sm"
                }
              >
                Abrir na loja
              </a>
            ) : null}
          </div>
        </div>
      </div>
    </div>
  );
}

export function ExplorarOfertas() {
  const [termo, setTermo] = useState("");
  const [marketplace, setMarketplace] = useState("");
  const [precoMin, setPrecoMin] = useState("");
  const [precoMax, setPrecoMax] = useState("");
  const [armazenamento, setArmazenamento] = useState("");
  const [loading, setLoading] = useState(false);
  const [erro, setErro] = useState<string | null>(null);
  const [resultado, setResultado] = useState<{ total: number; items: OfertaFiltrada[] } | null>(
    null
  );

  async function onSubmit(e: FormEvent) {
    e.preventDefault();
    setErro(null);

    const pMin = precoMin.trim() ? Number(precoMin.replace(",", ".")) : undefined;
    const pMax = precoMax.trim() ? Number(precoMax.replace(",", ".")) : undefined;
    if (pMin != null && Number.isNaN(pMin)) {
      setErro("Preço mínimo inválido.");
      return;
    }
    if (pMax != null && Number.isNaN(pMax)) {
      setErro("Preço máximo inválido.");
      return;
    }
    if (pMin != null && pMax != null && pMin > pMax) {
      setErro("O preço mínimo não pode ser maior que o máximo.");
      return;
    }

    const body: OfertasFiltrosRequest = { limite: 60 };
    const t = termo.trim();
    if (t) body.termo = t;
    if (marketplace === "amazon" || marketplace === "mercadolivre") {
      body.marketplace = marketplace;
    }
    if (pMin != null) body.preco_min = pMin;
    if (pMax != null) body.preco_max = pMax;
    const ag = armazenamento ? Number(armazenamento) : undefined;
    if (ag != null && !Number.isNaN(ag)) body.armazenamento_gb = ag;

    setLoading(true);
    try {
      const res = await filtrarOfertas(body);
      setResultado({ total: res.total, items: res.items });
    } catch (err) {
      setResultado(null);
      setErro(err instanceof Error ? err.message : "Falha ao buscar ofertas.");
    } finally {
      setLoading(false);
    }
  }

  function limpar() {
    setTermo("");
    setMarketplace("");
    setPrecoMin("");
    setPrecoMax("");
    setArmazenamento("");
    setErro(null);
    setResultado(null);
  }

  return (
    <div className="row justify-content-center">
      <div className="col-lg-10">
        <h1 className="h3 mb-2">Explorar ofertas</h1>
        <p className="text-muted mb-4">
          Filtre as ofertas já salvas no banco por marketplace, faixa de preço e armazenamento.
        </p>

        {erro ? <div className="alert alert-danger">{erro}</div> : null}

        <div className="card shadow-sm mb-4">
          <div className="card-body p-4">
            <form onSubmit={onSubmit}>
              <div className="row g-3">
                <div className="col-12">
                  <label className="form-label" htmlFor="filtro-termo">
                    Modelo ou produto
                  </label>
                  <input
                    id="filtro-termo"
                    className="form-control"
                    value={termo}
                    onChange={(e) => setTermo(e.target.value)}
                    placeholder="Ex.: iPhone 16, Galaxy S24…"
                    disabled={loading}
                    autoComplete="off"
                  />
                  <div className="form-text">Opcional. Busca no nome do produto e no modelo cadastrado.</div>
                </div>

                <div className="col-md-6">
                  <label className="form-label" htmlFor="filtro-marketplace">
                    Marketplace
                  </label>
                  <select
                    id="filtro-marketplace"
                    className="form-select"
                    value={marketplace}
                    onChange={(e) => setMarketplace(e.target.value)}
                    disabled={loading}
                  >
                    <option value="">Todos</option>
                    <option value="amazon">Amazon</option>
                    <option value="mercadolivre">Mercado Livre</option>
                  </select>
                </div>

                <div className="col-md-6">
                  <label className="form-label" htmlFor="filtro-armazenamento">
                    Armazenamento
                  </label>
                  <select
                    id="filtro-armazenamento"
                    className="form-select"
                    value={armazenamento}
                    onChange={(e) => setArmazenamento(e.target.value)}
                    disabled={loading}
                  >
                    {ARMAZENAMENTOS.map((a) => (
                      <option key={a.value || "any"} value={a.value}>
                        {a.label}
                      </option>
                    ))}
                  </select>
                </div>

                <div className="col-md-6">
                  <label className="form-label" htmlFor="filtro-preco-min">
                    Preço mínimo (R$)
                  </label>
                  <input
                    id="filtro-preco-min"
                    type="number"
                    min={0}
                    step={1}
                    className="form-control"
                    value={precoMin}
                    onChange={(e) => setPrecoMin(e.target.value)}
                    placeholder="Ex.: 2000"
                    disabled={loading}
                  />
                </div>

                <div className="col-md-6">
                  <label className="form-label" htmlFor="filtro-preco-max">
                    Preço máximo (R$)
                  </label>
                  <input
                    id="filtro-preco-max"
                    type="number"
                    min={0}
                    step={1}
                    className="form-control"
                    value={precoMax}
                    onChange={(e) => setPrecoMax(e.target.value)}
                    placeholder="Ex.: 6000"
                    disabled={loading}
                  />
                </div>
              </div>

              <div className="d-flex flex-wrap gap-2 mt-4">
                <button type="submit" className="btn btn-primary" disabled={loading}>
                  {loading ? "Buscando…" : "Buscar ofertas"}
                </button>
                <button
                  type="button"
                  className="btn btn-outline-secondary"
                  onClick={limpar}
                  disabled={loading}
                >
                  Limpar
                </button>
              </div>
            </form>
          </div>
        </div>

        {loading ? (
          <div className="text-center py-5">
            <div className="spinner-border text-primary" role="status">
              <span className="visually-hidden">Carregando…</span>
            </div>
          </div>
        ) : null}

        {resultado && !loading ? (
          <>
            <div className="d-flex justify-content-between align-items-center mb-3">
              <h2 className="h5 mb-0">
                {resultado.total === 0
                  ? "Nenhuma oferta encontrada"
                  : `${resultado.total} oferta${resultado.total === 1 ? "" : "s"} encontrada${resultado.total === 1 ? "" : "s"}`}
              </h2>
            </div>
            {resultado.total === 0 ? (
              <div className="alert alert-light border">
                Tente ampliar a faixa de preço, remover o marketplace ou mudar o armazenamento.
              </div>
            ) : (
              <div className="row g-4">
                {resultado.items.map((o) => (
                  <OfertaCard key={o.id} o={o} />
                ))}
              </div>
            )}
          </>
        ) : null}
      </div>
    </div>
  );
}

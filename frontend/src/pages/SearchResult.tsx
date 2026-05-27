import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import type { BuscaResponse, OfertaBusca } from "../api";
import { buscarNoBanco } from "../api";

function heroImage(data: BuscaResponse): string | undefined {
  const mc = data.mc as { imagem_url?: string } | null;
  if (mc?.imagem_url) return mc.imagem_url;
  const a0 = data.amazon[0]?.imagem_url;
  if (a0) return a0;
  return data.mercadolivre[0]?.imagem_url ?? undefined;
}

function SpecCard({ label, value }: { label: string; value: string }) {
  return (
    <div className="col-md-6 col-lg-4">
      <strong>{label}</strong>
      <br />
      {value || "—"}
    </div>
  );
}

function OfertaBloco({ o, origem }: { o: OfertaBusca; origem: "amazon" | "ml" }) {
  const dataTxt = o.data_extracao ?? o.data;
  return (
    <>
      <p className="text-muted small mb-2 fw-semibold">{o.rotulo_memoria || "Oferta"}</p>
      {o.imagem_url ? (
        <div className="text-center mb-3">
          <img
            src={o.imagem_url}
            alt=""
            className="img-fluid rounded border"
            style={{ maxHeight: 160, objectFit: "contain" }}
            loading="lazy"
            referrerPolicy="no-referrer"
          />
        </div>
      ) : null}
      <p className="fw-medium mb-2">{o.nome}</p>
      {dataTxt ? (
        <p className="small text-muted mb-2">
          Dados obtidos em <strong>{dataTxt}</strong>
        </p>
      ) : null}
      <p className="mb-1">
        <strong>Preço:</strong> {o.preco || "—"}
      </p>
      <p className="mb-1">
        <strong>Memória:</strong> {o.memoria || "—"}
      </p>
      {origem === "ml" ? (
        <>
          <p className="mb-1">
            <strong>Vendedor:</strong> {o.vendedor || "—"}
          </p>
          <p className="mb-3">
            <strong>Reputação:</strong> {o.reputacao || "—"}
          </p>
        </>
      ) : (
        <div className="mb-3" />
      )}
      {o.link ? (
        <a
          className={origem === "amazon" ? "btn btn-warning text-dark w-100" : "btn btn-success w-100"}
          href={o.link}
          target="_blank"
          rel="noopener noreferrer"
        >
          {origem === "amazon" ? "Ver na Amazon" : "Ver no Mercado Livre"}
        </a>
      ) : null}
    </>
  );
}

export function SearchResult() {
  const navigate = useNavigate();
  const { termo: termoParam } = useParams<{ termo: string }>();
  const termo = termoParam ? decodeURIComponent(termoParam) : "";
  const [data, setData] = useState<BuscaResponse | null>(null);
  const [erro, setErro] = useState<string | null>(null);

  useEffect(() => {
    if (!termo) return;
    let cancel = false;
    (async () => {
      setErro(null);
      try {
        const r = await buscarNoBanco(termo);
        if (!cancel) setData(r);
      } catch (e) {
        if (!cancel) setErro(e instanceof Error ? e.message : "Erro ao carregar resultado.");
      }
    })();
    return () => {
      cancel = true;
    };
  }, [termo]);

  if (!termo) {
    return (
      <div className="mb-3">
        <button type="button" className="btn btn-outline-secondary" onClick={() => navigate("/")}>
          &larr; Voltar
        </button>
      </div>
    );
  }

  if (erro) {
    return (
      <>
        <div className="mb-3">
          <button type="button" className="btn btn-outline-secondary" onClick={() => navigate("/")}>
            &larr; Nova busca
          </button>
        </div>
        <div className="alert alert-warning">{erro}</div>
      </>
    );
  }

  if (!data) {
    return (
      <div className="text-center py-5">
        <div className="spinner-border text-primary" role="status" />
      </div>
    );
  }

  const mc = data.mc as Record<string, string | null | undefined> | null;
  const titulo = (mc?.modelo as string) || data.termo;
  const imgHero = heroImage(data);

  return (
    <>
      <div className="mb-3">
        <button type="button" className="btn btn-outline-secondary" onClick={() => navigate("/")}>
          &larr; Nova busca
        </button>
      </div>

      <div className="bg-white rounded-3 shadow-sm p-4 mb-4">
        <div className="row g-3 align-items-center">
          {imgHero ? (
            <>
              <div className="col-sm-4 col-md-3 text-center">
                <img
                  src={imgHero}
                  alt={titulo}
                  className="img-fluid rounded border"
                  style={{ maxHeight: 220, objectFit: "contain" }}
                  loading="lazy"
                  referrerPolicy="no-referrer"
                />
              </div>
              <div className="col">
                <h1 className="h3 mb-1">{titulo}</h1>
                {mc?.data ? (
                  <p className="small mb-0 text-secondary">
                    <strong>Ficha técnica</strong> · dados obtidos em <strong>{mc.data}</strong>
                  </p>
                ) : null}
              </div>
            </>
          ) : (
            <div className="col-12">
              <h1 className="h3 mb-1">{titulo}</h1>
            </div>
          )}
        </div>
      </div>

      <section className="mb-5">
        <h2 className="h5 mb-3">Especificações</h2>
        <div className="card border-primary border-opacity-25">
          <div className="card-header bg-primary text-white py-2 d-flex justify-content-between align-items-center flex-wrap gap-2">
            <span>Mais Celular</span>
            {mc?.data ? <span className="small fw-normal opacity-90">Extraído em {mc.data}</span> : null}
          </div>
          <div className="card-body">
            {mc ? (
              <>
                {mc.imagem_url && mc.imagem_url !== imgHero ? (
                  <div className="text-center mb-3">
                    <img
                      src={mc.imagem_url}
                      alt={String(mc.modelo)}
                      className="img-fluid rounded border"
                      style={{ maxHeight: 180, objectFit: "contain" }}
                      loading="lazy"
                      referrerPolicy="no-referrer"
                    />
                  </div>
                ) : null}
                <div className="row g-3 small">
                  <SpecCard label="AnTuTu" value={String(mc.antutu ?? "")} />
                  <SpecCard label="Geekbench" value={String(mc.geekbench ?? "")} />
                  <SpecCard label="Chipset" value={String(mc.processador ?? "")} />
                  <SpecCard label="Sistema" value={String(mc.sistema_operacional ?? "")} />
                  <SpecCard label="RAM" value={String(mc.memoria_ram ?? "")} />
                  <SpecCard label="Armazenamento" value={String(mc.armazenamento ?? "")} />
                  <div className="col-12">
                    <strong>Tela</strong>
                    <br />
                    {mc.tela || "—"}
                  </div>
                  <div className="col-md-6">
                    <strong>Câmera traseira</strong>
                    <br />
                    {mc.camera_traseira || "—"}
                  </div>
                  <div className="col-md-6">
                    <strong>Câmera frontal</strong>
                    <br />
                    {mc.camera_frontal || "—"}
                  </div>
                  <div className="col-12">
                    <strong>Conectividade</strong>
                    <br />
                    {mc.conectividade || "—"}
                  </div>
                  <SpecCard label="Bateria" value={String(mc.bateria ?? "")} />
                  <SpecCard label="Carregamento" value={String(mc.carregamento ?? "")} />
                  <div className="col-md-6 col-lg-4">
                    <strong>Dimensões / peso</strong>
                    <br />
                    {(mc.dimensoes || "—") + " · " + (mc.peso || "—")}
                  </div>
                </div>
                {mc.url ? (
                  <p className="mt-3 mb-0">
                    <a href={mc.url} target="_blank" rel="noopener noreferrer">
                      Abrir ficha no Mais Celular
                    </a>
                  </p>
                ) : null}
              </>
            ) : (
              <p className="text-muted mb-0">Sem dados de ficha técnica.</p>
            )}
          </div>
        </div>
      </section>

      <section>
        <h2 className="h5 mb-3">Onde comprar</h2>
        <div className="row g-4">
          <div className="col-md-6">
            <div className="card h-100 border-warning border-opacity-50">
              <div className="card-header bg-warning text-dark fw-semibold">Amazon</div>
              <div className="card-body">
                {data.amazon.length ? (
                  data.amazon.map((amz, i) => (
                    <div key={i}>
                      {i > 0 ? <hr className="my-4" /> : null}
                      <OfertaBloco o={amz} origem="amazon" />
                    </div>
                  ))
                ) : (
                  <p className="text-muted mb-0">Nenhuma oferta encontrada.</p>
                )}
              </div>
            </div>
          </div>
          <div className="col-md-6">
            <div className="card h-100 border-success border-opacity-50">
              <div className="card-header bg-success text-white fw-semibold">Mercado Livre</div>
              <div className="card-body">
                {data.mercadolivre.length ? (
                  data.mercadolivre.map((ml, i) => (
                    <div key={i}>
                      {i > 0 ? <hr className="my-4" /> : null}
                      <OfertaBloco o={ml} origem="ml" />
                    </div>
                  ))
                ) : (
                  <p className="text-muted mb-0">Nenhuma oferta encontrada.</p>
                )}
              </div>
            </div>
          </div>
        </div>
      </section>
    </>
  );
}

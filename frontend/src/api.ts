export type OfertaBusca = {
  nome: string;
  memoria?: string | null;
  rotulo_memoria?: string | null;
  preco?: string | null;
  link?: string | null;
  imagem_url?: string | null;
  data_extracao?: string | null;
  data?: string | null;
  vendedor?: string | null;
  reputacao?: string | null;
};

export type BuscaResponse = {
  termo: string;
  limite_ofertas: number;
  mc: Record<string, unknown> | null;
  amazon: OfertaBusca[];
  mercadolivre: OfertaBusca[];
};

export type AparelhoLista = {
  id: number;
  modelo: string;
  termo_busca: string;
  extraido_em_texto: string | null;
  criado_em: string | null;
};

export type AparelhoDetalhe = Record<string, unknown> & {
  id: number;
  modelo?: string;
  especificacoes_json?: Record<string, unknown>;
};

export type OfertaLista = {
  id: number;
  origem: string;
  nome_produto: string;
  preco: string | null;
  extraido_em_texto: string | null;
  criado_em: string | null;
};

export type OfertaDetalhe = {
  id: number;
  origem: string;
  termo_busca: string;
  nome_produto: string;
  memoria: string | null;
  preco: string | null;
  link: string | null;
  imagem_url: string | null;
  vendedor: string | null;
  reputacao: string | null;
  reputacao_nivel: string | null;
  vendas_aprox: string | null;
  extraido_em_texto: string | null;
  aparelho_id: number | null;
  aparelho?: AparelhoDetalhe | null;
  criado_em: string | null;
};

async function parseError(res: Response): Promise<string> {
  try {
    const j = (await res.json()) as { detail?: unknown };
    if (typeof j.detail === "string") return j.detail;
    if (Array.isArray(j.detail)) return JSON.stringify(j.detail);
  } catch {
    /* ignore */
  }
  return res.statusText || "Erro na requisição";
}

export async function buscarNoBanco(termo: string): Promise<BuscaResponse> {
  const res = await fetch("/api/buscar", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ termo }),
  });
  if (!res.ok) throw new Error(await parseError(res));
  return res.json() as Promise<BuscaResponse>;
}

export async function listarAparelhos(): Promise<{ items: AparelhoLista[] }> {
  const res = await fetch("/api/aparelhos");
  if (!res.ok) throw new Error(await parseError(res));
  return res.json() as Promise<{ items: AparelhoLista[] }>;
}

export async function getAparelho(id: number): Promise<AparelhoDetalhe> {
  const res = await fetch(`/api/aparelhos/${id}`);
  if (!res.ok) throw new Error(await parseError(res));
  return res.json() as Promise<AparelhoDetalhe>;
}

export async function excluirAparelho(id: number): Promise<void> {
  const res = await fetch(`/api/aparelhos/${id}`, { method: "DELETE" });
  if (!res.ok) throw new Error(await parseError(res));
}

export type OfertasFiltrosRequest = {
  termo?: string;
  marketplace?: "amazon" | "mercadolivre";
  preco_min?: number;
  preco_max?: number;
  armazenamento_gb?: number;
  limite?: number;
};

export type OfertaFiltrada = {
  id: number;
  origem: string;
  nome: string;
  memoria?: string | null;
  rotulo_memoria?: string | null;
  preco?: string | null;
  preco_valor?: number | null;
  link?: string | null;
  imagem_url?: string | null;
  armazenamento_gb?: number | null;
  aparelho?: {
    id: number;
    modelo: string;
    armazenamento?: string | null;
    memoria_ram?: string | null;
  };
};

export type OfertasFiltrosResponse = {
  filtros: Record<string, unknown>;
  total: number;
  items: OfertaFiltrada[];
};

export async function filtrarOfertas(
  body: OfertasFiltrosRequest
): Promise<OfertasFiltrosResponse> {
  const payload: Record<string, unknown> = {};
  const t = body.termo?.trim();
  if (t) payload.termo = t;
  if (body.marketplace) payload.marketplace = body.marketplace;
  if (body.preco_min != null && body.preco_min >= 0) payload.preco_min = body.preco_min;
  if (body.preco_max != null && body.preco_max >= 0) payload.preco_max = body.preco_max;
  if (body.armazenamento_gb != null && body.armazenamento_gb > 0) {
    payload.armazenamento_gb = body.armazenamento_gb;
  }
  if (body.limite != null) payload.limite = body.limite;

  const res = await fetch("/api/ofertas/filtros", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!res.ok) throw new Error(await parseError(res));
  return res.json() as Promise<OfertasFiltrosResponse>;
}

export async function listarOfertas(): Promise<{ items: OfertaLista[] }> {
  const res = await fetch("/api/ofertas");
  if (!res.ok) throw new Error(await parseError(res));
  return res.json() as Promise<{ items: OfertaLista[] }>;
}

export async function getOferta(id: number): Promise<OfertaDetalhe> {
  const res = await fetch(`/api/ofertas/${id}`);
  if (!res.ok) throw new Error(await parseError(res));
  return res.json() as Promise<OfertaDetalhe>;
}

export async function excluirOferta(id: number): Promise<void> {
  const res = await fetch(`/api/ofertas/${id}`, { method: "DELETE" });
  if (!res.ok) throw new Error(await parseError(res));
}

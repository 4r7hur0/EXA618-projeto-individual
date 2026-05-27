import type { AparelhoDetalhe } from "../api";

function str(v: unknown): string {
  if (v == null || v === "") return "—";
  return String(v);
}

const CAMPOS = [
  ["AnTuTu", "antutu"],
  ["Geekbench", "geekbench"],
  ["Chipset", "processador"],
  ["Sistema", "sistema_operacional"],
  ["RAM", "memoria_ram"],
  ["Armazenamento", "armazenamento"],
  ["Tela", "tela"],
  ["Câmera traseira", "camera_traseira"],
  ["Câmera frontal", "camera_frontal"],
  ["Conectividade", "conectividade"],
  ["Bateria", "bateria"],
  ["Carregamento", "carregamento"],
  ["Dimensões", "dimensoes"],
  ["Peso", "peso"],
  ["Áudio", "audio"],
  ["Biometria", "biometria"],
] as const;

type Props = {
  aparelho: AparelhoDetalhe;
  titulo?: string;
};

export function EspecificacoesAparelho({ aparelho, titulo = "Especificações do aparelho" }: Props) {
  const modelo = str(aparelho.modelo);
  const jsonPairs = Object.entries(aparelho.especificacoes_json || {});

  return (
    <section className="mt-4">
      <h2 className="h5 mb-3">{titulo}</h2>
      <p className="text-muted small mb-3">
        Ficha: <strong>{modelo}</strong>
        {aparelho.url ? (
          <>
            {" "}
            ·{" "}
            <a href={String(aparelho.url)} target="_blank" rel="noopener noreferrer">
              Mais Celular
            </a>
          </>
        ) : null}
      </p>

      <div className="row g-3">
        {CAMPOS.map(([label, key]) => {
          const v = aparelho[key as keyof AparelhoDetalhe];
          const col = key === "tela" || key === "conectividade" ? "col-12" : "col-md-6";
          return (
            <div className={col} key={key}>
              <div className="card p-3 h-100">
                <strong>{label}</strong>
                <br />
                {str(v)}
              </div>
            </div>
          );
        })}
      </div>

      {jsonPairs.length > 0 ? (
        <>
          <h3 className="h6 mt-4">Outros dados (JSON)</h3>
          <div className="table-responsive">
            <table className="table table-sm table-striped bg-white">
              <thead>
                <tr>
                  <th>Campo</th>
                  <th>Valor</th>
                </tr>
              </thead>
              <tbody>
                {jsonPairs.map(([k, v]) => (
                  <tr key={k}>
                    <td>{k}</td>
                    <td>{typeof v === "object" ? JSON.stringify(v) : String(v)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      ) : null}
    </section>
  );
}
